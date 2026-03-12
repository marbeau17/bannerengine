"""Preview routes - generate SVG previews for banner templates."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.core.exceptions import TemplateNotFoundError

logger = logging.getLogger("banner_engine")

router = APIRouter(prefix="/api/preview", tags=["preview"])


@router.get("/{pattern_id}", response_class=HTMLResponse)
async def preview_banner(request: Request, pattern_id: str):
    """Generate an SVG preview for the current session's slot values.

    Retrieves the template definition and the user's current slot values
    from the session, then renders an SVG representation via the
    SvgRenderer service. Returns the SVG wrapped in an HTML div suitable
    for htmx swap into the preview canvas area.
    """
    template_service = request.app.state.template_service
    template = template_service.get_template(pattern_id)



    slot_values = request.session.get(f"slots_{pattern_id}", {})

    svg_renderer = request.app.state.svg_renderer
    svg_string = svg_renderer.render(template, slot_values)

    html_content = f'<div id="preview-canvas">{svg_string}</div>'
    return HTMLResponse(content=html_content)
