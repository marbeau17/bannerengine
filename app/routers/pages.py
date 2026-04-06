"""Page rendering routes - returns full HTML pages."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.core.exceptions import TemplateNotFoundError
from app.models.template import Slot, SlotType

router = APIRouter(tags=["pages"])

templates = Jinja2Templates(directory="app/templates")


def _build_sidebar_layers(template, slot_values: dict) -> tuple[list, list]:
    """Return (sidebar_layers, display_slots) for the editor page.

    sidebar_layers — unified, Photoshop-ordered list of lightweight dicts
                     covering both template slots and custom layers.  Used
                     by the left-sidebar layer list.
    display_slots  — template slots only (non-hidden), same order, used by
                     the right-side slot editor and AI tab.

    Each sidebar_layers entry has: id, kind ("slot"|"custom"), type_value,
    required, label.
    """
    saved_order = slot_values.get("_order") or []
    custom_layers = slot_values.get("_custom_layers") or []

    # --- Build raw item pool ---
    slot_map = {s.id: s for s in template.slots}
    custom_map = {layer["id"]: layer for layer in custom_layers if isinstance(layer, dict)}

    # Start with saved order, then append anything not yet listed
    all_ids_ordered: list[str] = list(saved_order)
    for s in template.slots:
        if s.id not in all_ids_ordered:
            all_ids_ordered.append(s.id)
    for layer in custom_layers:
        lid = layer.get("id", "") if isinstance(layer, dict) else ""
        if lid and lid not in all_ids_ordered:
            all_ids_ordered.append(lid)

    # Reverse for Photoshop display (last in draw order = top of sidebar)
    display_ids = list(reversed(all_ids_ordered))

    sidebar_layers: list[dict] = []
    for sid in display_ids:
        if sid in slot_map:
            slot = slot_map[sid]
            val = slot_values.get(sid)
            if isinstance(val, dict) and val.get("_hidden"):
                continue  # skip hidden template slots
            sidebar_layers.append({
                "id": slot.id,
                "kind": "slot",
                "type_value": slot.type.value,
                "required": getattr(slot, "required", False),
                "label": slot.id,
            })
        elif sid in custom_map:
            layer = custom_map[sid]
            sidebar_layers.append({
                "id": layer["id"],
                "kind": "custom",
                "type_value": layer.get("type", "rect"),
                "required": False,
                "label": layer.get("text", layer.get("label", layer["id"])),
            })

    # display_slots: template slots (non-hidden) + all editable custom layers, in sidebar order
    # Custom layers are synthesized as Slot objects with is_custom=True so they feed into
    # the right-side slot editor tab using the same Jinja templates.
    _SLOT_TYPE_MAP = {
        "image": SlotType.IMAGE,
        "text": SlotType.TEXT,
        "rect": SlotType.RECT,
        "circle": SlotType.CIRCLE,
    }
    display_slots: list[Slot] = []
    for entry in sidebar_layers:
        if entry["kind"] == "slot":
            slot = slot_map.get(entry["id"])
            if slot:
                display_slots.append(slot)
        elif entry["kind"] == "custom" and entry["type_value"] in _SLOT_TYPE_MAP:
            layer = custom_map.get(entry["id"])
            if not layer:
                continue
            layer_type = layer.get("type", "rect")
            slot_type = _SLOT_TYPE_MAP.get(layer_type, SlotType.RECT)
            synth = Slot(
                id=layer["id"],
                type=slot_type,
                x=float(layer.get("x", 10)),
                y=float(layer.get("y", 10)),
                width=float(layer.get("width", 30)),
                height=float(layer.get("height", 20)),
                description="",
                required=False,
                is_custom=True,
            )
            display_slots.append(synth)

    return sidebar_layers, display_slots


@router.get("/", response_class=HTMLResponse)
async def home(request: Request):
    """Home / template selection page."""
    template_service = request.app.state.template_service
    categories = template_service.get_categories()
    all_templates = template_service.list_templates()

    return templates.TemplateResponse(
        request,
        "pages/index.html",
        {
            "categories": categories,
            "templates": all_templates,
        },
    )


def _flatten_slot_values(slot_values: dict) -> dict:
    """Return a copy of slot_values with custom layer data keyed by layer ID at top level.

    The slot editor partial looks up values via ``slot_values.get(slot.id, {})``.
    For synthesized custom Slot objects their id is e.g. ``custom_abc123``, but the
    actual data lives inside ``slot_values["_custom_layers"]``.  This function
    merges those entries up so the template can find them with a plain dict lookup.
    """
    flat = dict(slot_values)
    for layer in slot_values.get("_custom_layers") or []:
        if not isinstance(layer, dict):
            continue
        lid = layer.get("id")
        if lid and lid not in flat:
            # Expose as a value dict matching what slot editor templates expect
            layer_type = layer.get("type", "rect")
            opacity = layer.get("opacity", 1.0)
            if layer_type == "text":
                flat[lid] = {"text": layer.get("text", ""), "color": layer.get("color", "#111111"),
                             "font_size": layer.get("font_size", "24"), "opacity": opacity}
            elif layer_type == "image":
                flat[lid] = {"source_url": layer.get("source_url", ""), "opacity": opacity}
            elif layer_type in ("rect", "circle"):
                flat[lid] = {"fill": layer.get("fill", "#4f46e5"), "opacity": opacity}
    return flat


@router.get("/api/pages/slot-editor/{pattern_id}", response_class=HTMLResponse)
async def slot_editor_partial(request: Request, pattern_id: str):
    """Return a freshly rendered slot_editor.html partial (OOB sync after AI pipeline)."""
    template_service = request.app.state.template_service
    template = template_service.get_template(pattern_id)
    slot_values = request.session.get(f"slots_{pattern_id}", {})

    _, display_slots = _build_sidebar_layers(template, slot_values)
    flat_slot_values = _flatten_slot_values(slot_values)

    return templates.TemplateResponse(
        request,
        "partials/slot_editor.html",
        {"slots": display_slots, "slot_values": flat_slot_values, "pattern_id": pattern_id},
    )


@router.get("/editor/{pattern_id}", response_class=HTMLResponse)
async def editor(request: Request, pattern_id: str):
    """Editor page for a specific banner template."""
    template_service = request.app.state.template_service
    svg_renderer = request.app.state.svg_renderer
    template = template_service.get_template(pattern_id)

    slot_values = request.session.get(f"slots_{pattern_id}", {})

    # Pre-render SVG
    try:
        effective_template = template
        design_overrides = slot_values.get("_design")
        if isinstance(design_overrides, dict) and design_overrides.get("background_value"):
            effective_template = template.model_copy(deep=True)
            effective_template.design.background_value = design_overrides["background_value"]
        svg_markup = svg_renderer.render(effective_template, slot_values)
    except Exception:
        svg_markup = None

    sidebar_layers, display_slots = _build_sidebar_layers(template, slot_values)
    custom_layers = list(slot_values.get("_custom_layers") or [])
    flat_slot_values = _flatten_slot_values(slot_values)

    return templates.TemplateResponse(
        request,
        "pages/editor.html",
        {
            "template": template,
            "pattern_id": pattern_id,
            "slots": display_slots,
            "sidebar_layers": sidebar_layers,
            "custom_layers": custom_layers,
            "slot_values": flat_slot_values,
            "svg_markup": svg_markup,
        },
    )
