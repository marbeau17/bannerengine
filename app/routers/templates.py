"""Template API routes - returns HTML partials for htmx."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.core.exceptions import TemplateNotFoundError

router = APIRouter(prefix="/api/templates", tags=["templates"])

templates = Jinja2Templates(directory="app/templates")


@router.get("", response_class=HTMLResponse)
async def list_templates(
    request: Request,
    category: Optional[str] = Query(None, description="Filter by category"),
    q: Optional[str] = Query(None, description="Search query"),
):
    """Return template cards partial (HTML fragment for htmx swap).

    Supports optional filtering by category and free-text search.
    """
    template_service = request.app.state.template_service
    all_templates = template_service.list_templates()

    # Apply category filter
    if category:
        all_templates = [
            t for t in all_templates if t.meta.category.lower() == category.lower()
        ]

    # Apply search filter
    if q:
        query_lower = q.lower()
        all_templates = [
            t
            for t in all_templates
            if query_lower in t.meta.pattern_name.lower()
            or query_lower in t.meta.category.lower()
            or query_lower in t.meta.recommended_use.lower()
        ]

    return templates.TemplateResponse(
        "partials/template_grid.html",
        {
            "request": request,
            "templates": all_templates,
        },
    )


@router.get("/categories", response_class=HTMLResponse)
async def list_categories(request: Request):
    """Return category list partial (HTML fragment for htmx swap)."""
    template_service = request.app.state.template_service
    categories = template_service.get_categories()

    return templates.TemplateResponse(
        "partials/category_list.html",
        {
            "request": request,
            "categories": categories,
        },
    )


@router.get("/{pattern_id}", response_class=HTMLResponse)
async def get_template_detail(request: Request, pattern_id: str):
    """Return template detail partial (HTML fragment for htmx swap)."""
    template_service = request.app.state.template_service
    template = template_service.get_template(pattern_id)


    return templates.TemplateResponse(
        "partials/template_detail.html",
        {
            "request": request,
            "template": template,
            "pattern_id": pattern_id,
        },
    )


@router.get("/{pattern_id}/slots", response_class=HTMLResponse)
async def get_slot_editors(request: Request, pattern_id: str):
    """Return slot editor forms partial (HTML fragment for htmx swap)."""
    template_service = request.app.state.template_service
    template = template_service.get_template(pattern_id)


    slot_values = request.session.get(f"slots_{pattern_id}", {})

    return templates.TemplateResponse(
        "partials/slot_editor.html",
        {
            "request": request,
            "template": template,
            "pattern_id": pattern_id,
            "slots": template.slots,
            "slot_values": slot_values,
        },
    )
