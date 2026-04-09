"""Freeform layer management — spawn/edit/delete custom layers on the canvas."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

router = APIRouter(prefix="/api/layers", tags=["layers"])
templates = Jinja2Templates(directory="app/templates")

# Default geometry and style for each layer type
_LAYER_DEFAULTS: dict[str, dict] = {
    "rect":   {"fill": "#4f46e5", "label": "Rectangle"},
    "circle": {"fill": "#059669", "label": "Circle"},
    "text":   {"text": "Text Layer", "color": "#111111", "font_size": "24"},
    "image":  {"source_url": "", "label": "Image Layer"},
}


def _get_custom_layers(request: Request, pattern_id: str) -> list:
    return list(request.session.get(f"slots_{pattern_id}", {}).get("_custom_layers", []))


def _save_custom_layers(request: Request, pattern_id: str, layers: list) -> None:
    slots = dict(request.session.get(f"slots_{pattern_id}", {}))
    slots["_custom_layers"] = layers
    request.session[f"slots_{pattern_id}"] = slots


def _render_canvas(request: Request, pattern_id: str) -> HTMLResponse:
    """Re-render canvas + OOB left sidebar + OOB right slot-editor-panel."""
    import logging as _logging
    _log = _logging.getLogger("banner_engine")

    from app.routers.pages import _build_sidebar_layers, _flatten_slot_values

    template_service = request.app.state.template_service
    svg_renderer = request.app.state.svg_renderer
    template = template_service.get_template(pattern_id)
    slot_values = dict(request.session.get(f"slots_{pattern_id}", {}))

    cl = slot_values.get("_custom_layers", [])
    _log.info("_render_canvas: %d custom layers in session", len(cl))
    if cl:
        _log.info("_render_canvas: first layer id=%s source_url=%s", cl[0].get("id"), cl[0].get("source_url"))

    svg_markup = svg_renderer.render(template, slot_values)

    canvas_html = templates.env.get_template("partials/preview_canvas.html").render(
        request=request,
        template=template,
        pattern_id=pattern_id,
        svg_markup=svg_markup,
    )

    sidebar_layers, display_slots = _build_sidebar_layers(template, slot_values)
    flat_slot_values = _flatten_slot_values(slot_values)

    # OOB 1: left layer list
    sidebar_html = templates.env.get_template("partials/layer_sidebar.html").render(
        request=request,
        sidebar_layers=sidebar_layers,
        pattern_id=pattern_id,
    )

    # OOB 2: right slot-editor-panel — wrap in a div with the panel's id so
    # HTMX (and applyCanvasResponse) knows where to swap it
    slot_editor_inner = templates.env.get_template("partials/slot_editor.html").render(
        request=request,
        template=template,
        slots=display_slots,
        slot_values=flat_slot_values,
        pattern_id=pattern_id,
    )
    slot_editor_oob = (
        f'<div id="slot-editor-panel" hx-swap-oob="true">{slot_editor_inner}</div>'
    )

    # OOB 3: AI tab slot list — targets the inner wrapper to avoid resetting
    # panel-ai's hidden class (which JS controls for tab switching)
    ai_tab_inner = templates.env.get_template("partials/ai_tab.html").render(
        request=request,
        slots=display_slots,
        pattern_id=pattern_id,
    )
    ai_tab_oob = f'<div id="ai-tab-slots" hx-swap-oob="true">{ai_tab_inner}</div>'

    return HTMLResponse(content=canvas_html + sidebar_html + slot_editor_oob + ai_tab_oob)


@router.post("/{pattern_id}", response_class=HTMLResponse)
async def add_layer(request: Request, pattern_id: str):
    """Spawn a new freeform layer and return a refreshed preview canvas."""
    form = await request.form()
    layer_type = str(form.get("layer_type", "rect"))
    if layer_type not in _LAYER_DEFAULTS:
        layer_type = "rect"

    prefix = "shape" if layer_type in ("rect", "circle") else layer_type
    existing = _get_custom_layers(request, pattern_id)
    max_n = 0
    for l in existing:
        lid = l.get("id", "")
        if lid.startswith(f"custom_{prefix}_"):
            try:
                max_n = max(max_n, int(lid.split("_")[-1]))
            except ValueError:
                pass
    layer_id = f"custom_{prefix}_{max_n + 1}"
    new_layer: dict = {
        "id": layer_id,
        "type": layer_type,
        "x": 10.0,
        "y": 10.0,
        "width": 30.0,
        "height": 20.0,
        "opacity": 1.0,
        "blend_mode": "normal",
        **_LAYER_DEFAULTS[layer_type],
    }

    layers = _get_custom_layers(request, pattern_id)
    layers.append(new_layer)
    _save_custom_layers(request, pattern_id, layers)

    # Auto-stack: insert new layer at the FRONT of _order so it appears at the
    # top of the Photoshop-style sidebar (_order is front-to-back, index 0 = top).
    slots = dict(request.session.get(f"slots_{pattern_id}", {}))
    order: list = list(slots.get("_order", []))
    if layer_id not in order:
        order.insert(0, layer_id)
    slots["_order"] = order
    request.session[f"slots_{pattern_id}"] = slots

    return _render_canvas(request, pattern_id)


@router.delete("/{pattern_id}/{layer_id}", response_class=HTMLResponse)
async def delete_layer(request: Request, pattern_id: str, layer_id: str):
    """Remove a freeform layer and return a refreshed preview canvas."""
    layers = [l for l in _get_custom_layers(request, pattern_id) if l["id"] != layer_id]
    _save_custom_layers(request, pattern_id, layers)
    return _render_canvas(request, pattern_id)


@router.patch("/{pattern_id}/{layer_id}", response_class=HTMLResponse)
async def update_layer(request: Request, pattern_id: str, layer_id: str):
    """Edit a freeform layer's properties and return a refreshed preview canvas."""
    form = await request.form()
    layers = _get_custom_layers(request, pattern_id)
    _NUMERIC_FIELDS = {"x", "y", "width", "height", "opacity", "rotation"}
    for layer in layers:
        if layer["id"] == layer_id:
            for field in ("fill", "color", "opacity", "blend_mode", "text", "font_size", "source_url", "x", "y", "width", "height", "rotation"):
                val = form.get(field)
                if val is not None:
                    if field in _NUMERIC_FIELDS:
                        fval = float(val)
                        # Opacity arrives as 0-100 from the range slider — normalise to 0.0-1.0
                        if field == "opacity" and fval > 1.0:
                            fval = round(fval / 100.0, 2)
                        layer[field] = fval
                    else:
                        layer[field] = str(val)
            # Map `content` (slot editor convention) → `text` for custom text layers
            content_val = form.get("content")
            if content_val is not None:
                layer["text"] = str(content_val)
            break
    _save_custom_layers(request, pattern_id, layers)
    return _render_canvas(request, pattern_id)
