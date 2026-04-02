"""Banner generation routes - start jobs and render SVG-based banners."""

from __future__ import annotations

import asyncio
import io
import logging
import os
import uuid

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.core.exceptions import TemplateNotFoundError, ValidationError

logger = logging.getLogger("banner_engine")

router = APIRouter(prefix="/api/generate", tags=["generate"])

templates = Jinja2Templates(directory="app/templates")

# In-memory job store for the MVP. Maps job_id -> job state dict.
_jobs: dict[str, dict] = {}

OUTPUT_DIR = os.path.join("static", "generated")
os.makedirs(OUTPUT_DIR, exist_ok=True)


@router.post("/{pattern_id}", response_class=HTMLResponse)
async def start_generation(request: Request, pattern_id: str):
    """Start a banner generation job.

    Validates that all required slots are filled, renders the SVG,
    converts to PNG, and returns an HTML partial with progress polling.
    """
    template_service = request.app.state.template_service
    svg_renderer = request.app.state.svg_renderer
    template = template_service.get_template(pattern_id)

    slot_values = request.session.get(f"slots_{pattern_id}", {})

    # Validate all required slots are filled
    missing_slots = []
    for slot in template.slots:
        if slot.required and slot.id not in slot_values:
            missing_slots.append(slot.id)

    if missing_slots:
        # Return error as HTML partial instead of raising (htmx expects HTML)
        slot_names = ", ".join(missing_slots)
        return templates.TemplateResponse(
            request,
            "partials/generate_result.html",
            {
                "status": "error",
                "error": f"未入力の必須スロットがあります: {slot_names}",
            },
        )

    # Create a job entry
    job_id = str(uuid.uuid4())
    _jobs[job_id] = {
        "job_id": job_id,
        "pattern_id": pattern_id,
        "status": "processing",
        "progress": 0,
        "file_url": None,
    }

    # Kick off generation in background
    svg_string = svg_renderer.render(template, slot_values)
    asyncio.create_task(_render_banner(job_id, svg_string, template.meta.width, template.meta.height))

    return templates.TemplateResponse(
        request,
        "partials/generate_result.html",
        {
            "status": "processing",
            "job_id": job_id,
            "progress": 0,
        },
    )


async def _render_banner(job_id: str, svg_string: str, width: int, height: int) -> None:
    """Render the SVG to a PNG file using cairosvg or Pillow fallback."""
    job = _jobs[job_id]
    try:
        job["progress"] = 20
        await asyncio.sleep(0.1)

        # Embed local images as base64 data URIs so cairosvg can render them
        svg_for_render = await asyncio.to_thread(_embed_local_images, svg_string)

        png_bytes = await asyncio.to_thread(_svg_to_png, svg_for_render, width, height)
        job["progress"] = 80
        await asyncio.sleep(0.1)

        # Write file
        filename = f"{job_id}.png"
        filepath = os.path.join(OUTPUT_DIR, filename)
        with open(filepath, "wb") as f:
            f.write(png_bytes)

        job["file_url"] = f"/static/generated/{filename}"
        job["progress"] = 100
        job["status"] = "completed"

    except Exception as exc:
        logger.error("Banner rendering failed for job %s: %s", job_id, exc)
        job["status"] = "failed"
        job["error"] = str(exc)
        job["progress"] = 0


def _embed_local_images(svg_string: str) -> str:
    """Replace local /static/ image hrefs with inline base64 data URIs."""
    import base64
    import mimetypes
    import re

    def _replace_href(match: re.Match) -> str:
        path = match.group(1)
        # Only process local /static/ paths
        if not path.startswith("/static/"):
            return match.group(0)
        file_path = path.lstrip("/")  # "static/uploads/abc.png"
        if not os.path.isfile(file_path):
            return match.group(0)
        mime, _ = mimetypes.guess_type(file_path)
        if not mime:
            mime = "image/png"
        with open(file_path, "rb") as f:
            data = base64.b64encode(f.read()).decode()
        return f'href="data:{mime};base64,{data}"'

    return re.sub(r'href="([^"]+)"', _replace_href, svg_string)


def _svg_to_png(svg_string: str, width: int, height: int) -> bytes:
    """Convert SVG string to PNG bytes. Tries cairosvg first, falls back to
    writing the SVG as a simple PNG placeholder via Pillow."""
    try:
        import cairosvg
        return cairosvg.svg2png(bytestring=svg_string.encode("utf-8"),
                                output_width=width, output_height=height)
    except ImportError:
        pass

    # Fallback: render a simple PNG with the SVG embedded as text info
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("RGB", (width, height), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)

    # Draw a border
    draw.rectangle([0, 0, width - 1, height - 1], outline=(200, 200, 200), width=2)

    # Draw centered text
    text = "Banner Preview (install cairosvg for full render)"
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 20)
    except (OSError, IOError):
        font = ImageFont.load_default()
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(((width - tw) / 2, (height - th) / 2), text, fill=(100, 100, 100), font=font)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@router.get("/progress/{job_id}", response_class=HTMLResponse)
async def generation_progress(request: Request, job_id: str):
    """Return the current generation status as an HTML partial for htmx polling."""
    if job_id not in _jobs:
        return templates.TemplateResponse(
            request,
            "partials/generate_result.html",
            {"status": "error", "error": f"Job not found: {job_id}"},
        )

    job = _jobs[job_id]
    return templates.TemplateResponse(
        request,
        "partials/generate_result.html",
        {
            "status": job["status"],
            "job_id": job_id,
            "progress": job["progress"],
            "file_url": job.get("file_url"),
            "error": job.get("error"),
        },
    )
