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
        "pages/index.html",
        {
            "request": request,
            "categories": categories,
            "templates": all_templates,
        },
    )


@router.get("/editor/{pattern_id}", response_class=HTMLResponse)
async def editor(request: Request, pattern_id: str):
    """Editor page for a specific banner template.

    Renders the full editor UI with template details, slot editors,
    and a live preview canvas.
    """
    template_service = request.app.state.template_service
    template = template_service.get_template(pattern_id)

    # Retrieve any previously saved slot values from the session
    slot_values = request.session.get(f"slots_{pattern_id}", {})

    return templates.TemplateResponse(
        "pages/editor.html",
        {
            "request": request,
            "template": template,
            "pattern_id": pattern_id,
            "slots": template.slots,
            "slot_values": slot_values,
        },
    )
