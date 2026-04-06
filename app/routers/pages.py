"""Page rendering routes - returns full HTML pages."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.core.exceptions import TemplateNotFoundError

router = APIRouter(tags=["pages"])

templates = Jinja2Templates(directory="app/templates")


@router.get("/", response_class=HTMLResponse)
async def home(request: Request):
    """Home / template selection page.

    Renders the main landing page with category navigation and
    a grid of available banner templates.
    """
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


@router.get("/api/pages/slot-editor/{pattern_id}", response_class=HTMLResponse)
async def slot_editor_partial(request: Request, pattern_id: str):
    """Return a freshly rendered slot_editor.html partial.

    Called via HTMX hx-trigger=load after the AI blend pipeline completes
    (Phase 5 OOB sync) so newly generated text appears in the sidebar
    without a full page reload.
    """
    template_service = request.app.state.template_service
    template = template_service.get_template(pattern_id)
    slot_values = request.session.get(f"slots_{pattern_id}", {})

    # Apply the same Photoshop-order logic as the editor page
    saved_order = slot_values.get("_order")
    if saved_order and isinstance(saved_order, list):
        slot_map = {s.id: s for s in template.slots}
        ordered_slots = [slot_map[sid] for sid in saved_order if sid in slot_map]
        ordered_slots += [s for s in template.slots if s.id not in saved_order]
    else:
        ordered_slots = list(template.slots)
    display_slots = list(reversed(ordered_slots))

    return templates.TemplateResponse(
        request,
        "partials/slot_editor.html",
        {"slots": display_slots, "slot_values": slot_values, "pattern_id": pattern_id},
    )


@router.get("/editor/{pattern_id}", response_class=HTMLResponse)
async def editor(request: Request, pattern_id: str):
    """Editor page for a specific banner template.

    Renders the full editor UI with template details, slot editors,
    and a live preview canvas.
    """
    template_service = request.app.state.template_service
    svg_renderer = request.app.state.svg_renderer
    template = template_service.get_template(pattern_id)

    # Retrieve any previously saved slot values from the session
    slot_values = request.session.get(f"slots_{pattern_id}", {})

    # Pre-render the SVG so the canvas has draggable-slot groups from first load
    try:
        effective_template = template
        design_overrides = slot_values.get("_design")
        if isinstance(design_overrides, dict) and design_overrides.get("background_value"):
            effective_template = template.model_copy(deep=True)
            effective_template.design.background_value = design_overrides["background_value"]
        svg_markup = svg_renderer.render(effective_template, slot_values)
    except Exception:
        svg_markup = None

    # Build sidebar slot list respecting session draw order and Photoshop convention.
    # _order is stored in draw sequence (index 0 = bottom-most layer in SVG).
    # Reverse before passing to the template so that the highest-z-index slot
    # (the last to be drawn) sits at the top of the UI list — matching Photoshop.
    saved_order = slot_values.get("_order")
    if saved_order and isinstance(saved_order, list):
        slot_map = {s.id: s for s in template.slots}
        ordered_slots = [slot_map[sid] for sid in saved_order if sid in slot_map]
        # Include any slots not yet in the saved order (e.g. newly added)
        ordered_slots += [s for s in template.slots if s.id not in slot_map or s.id not in saved_order]
    else:
        ordered_slots = list(template.slots)
    display_slots = list(reversed(ordered_slots))

    return templates.TemplateResponse(
        request,
        "pages/editor.html",
        {
            "template": template,
            "pattern_id": pattern_id,
            "slots": display_slots,
            "slot_values": slot_values,
            "svg_markup": svg_markup,
        },
    )
