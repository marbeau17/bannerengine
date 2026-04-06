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
    return templates.TemplateResponse(
        request,
        "partials/slot_editor.html",
        {"slots": template.slots, "slot_values": slot_values, "pattern_id": pattern_id},
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

    return templates.TemplateResponse(
        request,
        "pages/editor.html",
        {
            "template": template,
            "pattern_id": pattern_id,
            "slots": template.slots,
            "slot_values": slot_values,
            "svg_markup": svg_markup,
        },
    )
