"""Banner generation routes - start jobs and render SVG-based banners."""

from __future__ import annotations

import asyncio
import base64
import io
import logging
import mimetypes
import os
import re
import uuid
import xml.etree.ElementTree as ET

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.core.exceptions import TemplateNotFoundError, ValidationError

logger = logging.getLogger("banner_engine")

router = APIRouter(prefix="/api/generate", tags=["generate"])

templates = Jinja2Templates(directory="app/templates")

# In-memory job store for the MVP. Maps job_id -> job state dict.
_jobs: dict[str, dict] = {}
_MAX_JOBS = 200

OUTPUT_DIR = os.path.join("static", "generated")
os.makedirs(OUTPUT_DIR, exist_ok=True)


def _evict_old_jobs() -> None:
    """Remove oldest completed/failed jobs when the store exceeds _MAX_JOBS."""
    if len(_jobs) <= _MAX_JOBS:
        return
    # Sort by completion: remove completed/failed first
    removable = [jid for jid, j in _jobs.items() if j["status"] in ("completed", "failed")]
    for jid in removable[:len(_jobs) - _MAX_JOBS]:
        _jobs.pop(jid, None)


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

    # Create a job entry (evict old ones if needed)
    _evict_old_jobs()
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
    """Convert SVG string to PNG bytes.

    Tries cairosvg first (best quality), then falls back to a pure-Python
    Pillow-based renderer that parses the SVG elements directly. The Pillow
    fallback works on Vercel and other environments without system Cairo libs.
    """
    try:
        import cairosvg
        return cairosvg.svg2png(bytestring=svg_string.encode("utf-8"),
                                output_width=width, output_height=height)
    except (ImportError, OSError):
        pass

    return _pillow_svg_render(svg_string, width, height)


_SVG_NS = "http://www.w3.org/2000/svg"
_XLINK_NS = "http://www.w3.org/1999/xlink"

# Font search paths (macOS, Linux)
_FONT_PATHS = [
    "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
    "/System/Library/Fonts/Helvetica.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]
_BOLD_FONT_PATHS = [
    "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/System/Library/Fonts/Helvetica.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]
_font_cache: dict[tuple, object] = {}

_NAMED_COLORS: dict[str, tuple[int, int, int, int]] = {
    "white": (255, 255, 255, 255), "black": (0, 0, 0, 255),
    "red": (255, 0, 0, 255), "blue": (0, 0, 255, 255),
    "green": (0, 128, 0, 255), "none": (0, 0, 0, 0),
}


def _get_font(size: float, bold: bool = False):
    """Get a font, using cache across renders."""
    from PIL import ImageFont

    key = (int(size), bold)
    if key in _font_cache:
        return _font_cache[key]
    sz = max(int(size), 8)
    for fp in (_BOLD_FONT_PATHS if bold else _FONT_PATHS) + _FONT_PATHS:
        try:
            font = ImageFont.truetype(fp, sz)
            _font_cache[key] = font
            return font
        except (OSError, IOError):
            continue
    font = ImageFont.load_default()
    _font_cache[key] = font
    return font


def _parse_color(color_str: str) -> tuple[int, int, int, int]:
    """Parse CSS color to RGBA tuple."""
    if not color_str:
        return (0, 0, 0, 255)
    color_str = color_str.strip()
    if color_str.startswith("#"):
        h = color_str.lstrip("#")
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        if len(h) == 6:
            return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), 255)
        if len(h) == 8:
            return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), int(h[6:8], 16))
    return _NAMED_COLORS.get(color_str.lower(), (0, 0, 0, 255))


def _pf(val: str | None, default: float = 0.0) -> float:
    """Parse a float from an SVG attribute value."""
    if val is None:
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def _pillow_svg_render(svg_string: str, width: int, height: int) -> bytes:
    """Pure-Python SVG to PNG renderer using Pillow.

    Parses SVG elements (rect, text, image) and draws them with Pillow.
    Handles the subset of SVG that our SvgRenderer produces, including
    clip-path clipping and preserveAspectRatio="xMidYMid slice" for images.
    """
    from PIL import Image, ImageDraw

    img = Image.new("RGBA", (width, height), (255, 255, 255, 255))
    draw = ImageDraw.Draw(img)

    try:
        root = ET.fromstring(svg_string)
    except ET.ParseError:
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    # Parse clip-path definitions from <defs>
    clip_rects: dict[str, tuple[float, float, float, float]] = {}
    for defs in root.iter(f"{{{_SVG_NS}}}defs"):
        for cp in defs.iter(f"{{{_SVG_NS}}}clipPath"):
            cp_id = cp.get("id", "")
            for rect in cp.iter(f"{{{_SVG_NS}}}rect"):
                cx = _pf(rect.get("x"))
                cy = _pf(rect.get("y"))
                cw = _pf(rect.get("width"))
                ch = _pf(rect.get("height"))
                clip_rects[cp_id] = (cx, cy, cw, ch)

    # Process elements in document order (skip defs children)
    def _process_children(parent: ET.Element) -> None:
        for elem in parent:
            tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag

            if tag == "defs":
                continue  # Already parsed above

            elif tag == "rect":
                x = _pf(elem.get("x"))
                y = _pf(elem.get("y"))
                w = _pf(elem.get("width"))
                h = _pf(elem.get("height"))

                # Clamp to canvas bounds
                x2 = min(x + w, width)
                y2 = min(y + h, height)
                if x2 <= x or y2 <= y:
                    continue

                fill = elem.get("fill", "#ffffff")
                fill_color = _parse_color(fill)

                if fill.lower() != "none" and fill_color[3] > 0:
                    opacity = elem.get("fill-opacity")
                    if opacity is not None:
                        fill_color = (*fill_color[:3], int(float(opacity) * 255))

                    rx = _pf(elem.get("rx"))
                    if rx > 0:
                        draw.rounded_rectangle([x, y, x2, y2], radius=int(rx), fill=fill_color)
                    else:
                        draw.rectangle([x, y, x2, y2], fill=fill_color)

                stroke = elem.get("stroke")
                if stroke and stroke.lower() != "none":
                    stroke_color = _parse_color(stroke)
                    stroke_w = max(int(_pf(elem.get("stroke-width"), 1)), 1)
                    dash = elem.get("stroke-dasharray")
                    # Pillow doesn't support dashed lines natively, draw solid
                    rx = _pf(elem.get("rx"))
                    if rx > 0:
                        draw.rounded_rectangle([x, y, x2, y2], radius=int(rx),
                                               outline=stroke_color, width=stroke_w)
                    else:
                        draw.rectangle([x, y, x2, y2], outline=stroke_color, width=stroke_w)

            elif tag == "text":
                x = _pf(elem.get("x"))
                y = _pf(elem.get("y"))
                fill = elem.get("fill", "#000000")
                fill_color = _parse_color(fill)
                font_size = _pf(elem.get("font-size"), 16)
                font_weight = elem.get("font-weight", "normal")
                text_content = elem.text or ""
                if not text_content.strip():
                    continue

                is_bold = font_weight.lower() in ("bold", "700", "800", "900")
                font = _get_font(font_size, bold=is_bold)
                anchor = elem.get("text-anchor", "start")

                bbox = draw.textbbox((0, 0), text_content, font=font)
                tw = bbox[2] - bbox[0]
                th = bbox[3] - bbox[1]

                tx = x
                if anchor == "middle":
                    tx = x - tw / 2
                elif anchor == "end":
                    tx = x - tw

                baseline = elem.get("dominant-baseline", "auto")
                ty = y
                if baseline == "central":
                    ty = y - th / 2
                elif baseline == "hanging":
                    pass
                else:
                    ty = y - th * 0.85  # Approximate alphabetic baseline

                draw.text((tx, ty), text_content, fill=fill_color[:3], font=font)

            elif tag == "image":
                href = elem.get("href") or elem.get(f"{{{_XLINK_NS}}}href", "")
                x = _pf(elem.get("x"))
                y = _pf(elem.get("y"))
                w = _pf(elem.get("width"))
                h = _pf(elem.get("height"))

                if not href or w <= 0 or h <= 0:
                    continue

                try:
                    img_bytes = _load_image_bytes(href)
                    if img_bytes is None:
                        continue

                    sub_img = Image.open(io.BytesIO(img_bytes)).convert("RGBA")

                    # Determine clip region
                    clip_ref = elem.get("clip-path", "")
                    clip_id = clip_ref.replace("url(#", "").rstrip(")") if clip_ref else ""
                    clip = clip_rects.get(clip_id)

                    # Use clip rect as the target area if available
                    target_x = clip[0] if clip else x
                    target_y = clip[1] if clip else y
                    target_w = clip[2] if clip else w
                    target_h = clip[3] if clip else h

                    # Implement preserveAspectRatio="xMidYMid slice":
                    # Scale image to cover the target area, then crop center
                    src_w, src_h = sub_img.size
                    scale = max(target_w / src_w, target_h / src_h)
                    scaled_w = int(src_w * scale)
                    scaled_h = int(src_h * scale)
                    sub_img = sub_img.resize((scaled_w, scaled_h), Image.LANCZOS)

                    # Crop to target dimensions from center
                    crop_x = (scaled_w - int(target_w)) // 2
                    crop_y = (scaled_h - int(target_h)) // 2
                    sub_img = sub_img.crop((
                        crop_x, crop_y,
                        crop_x + int(target_w), crop_y + int(target_h),
                    ))

                    img.paste(sub_img, (int(target_x), int(target_y)), sub_img)
                except Exception:
                    continue

            # Recurse into child elements (e.g. <g> groups)
            if len(elem) > 0 and tag not in ("text",):
                _process_children(elem)

    _process_children(root)

    # Convert RGBA to RGB
    output = Image.new("RGB", img.size, (255, 255, 255))
    output.paste(img, mask=img.split()[3])

    buf = io.BytesIO()
    output.save(buf, format="PNG", quality=95)
    return buf.getvalue()


def _load_image_bytes(href: str) -> bytes | None:
    """Load image bytes from a data URI, local path, or URL."""
    if href.startswith("data:"):
        _, b64data = href.split(",", 1)
        return base64.b64decode(b64data)
    elif href.startswith("/"):
        local_path = href.lstrip("/")
        if os.path.isfile(local_path):
            with open(local_path, "rb") as f:
                return f.read()
    elif href.startswith(("http://", "https://")):
        try:
            import httpx
            resp = httpx.get(href, timeout=10, follow_redirects=True)
            if resp.status_code == 200:
                return resp.content
        except Exception:
            pass
    return None


@router.post("/ai/{pattern_id}", response_class=HTMLResponse)
async def start_ai_generation(request: Request, pattern_id: str):
    """Start AI-enhanced banner generation using Nano Banana Pro.

    Renders the SVG preview to PNG as a reference image, then sends it
    to the AI model with a structured prompt to generate a polished version.
    Returns both the SVG-based and AI-generated versions for comparison.
    """
    template_service = request.app.state.template_service
    svg_renderer = request.app.state.svg_renderer
    banner_service = request.app.state.banner_service
    nano_client = request.app.state.nano_banana_client
    template = template_service.get_template(pattern_id)

    # Parse optional creative direction and tab mode from form data
    form = await request.form()
    creative_direction = str(form.get("creative_direction", "") or "").strip() or None
    mode = str(form.get("mode", "manual") or "manual").strip()
    if mode not in ("manual", "ai"):
        mode = "manual"

    slot_values = request.session.get(f"slots_{pattern_id}", {})

    missing_slots = [s.id for s in template.slots if s.required and s.id not in slot_values]
    if missing_slots:
        slot_names = ", ".join(missing_slots)
        return templates.TemplateResponse(
            request,
            "partials/generate_result.html",
            {"status": "error", "error": f"未入力の必須スロットがあります: {slot_names}"},
        )

    _evict_old_jobs()
    job_id = str(uuid.uuid4())
    _jobs[job_id] = {
        "job_id": job_id,
        "pattern_id": pattern_id,
        "status": "processing",
        "progress": 0,
        "file_url": None,
        "ai_file_url": None,
        "mode": "ai",
    }

    svg_string = svg_renderer.render(template, slot_values)
    render_instruction = banner_service.create_render_instruction(pattern_id, slot_values)

    # For custom templates, use the original uploaded image as AI reference
    custom_ref_url = request.session.get(f"custom_ref_{pattern_id}")
    custom_ref_bytes = None
    if custom_ref_url:
        ref_path = custom_ref_url.lstrip("/")
        if os.path.isfile(ref_path):
            with open(ref_path, "rb") as f:
                custom_ref_bytes = f.read()

    asyncio.create_task(_render_ai_banner(
        job_id, svg_string, template.meta.width, template.meta.height,
        render_instruction, nano_client, creative_direction, custom_ref_bytes, mode,
    ))

    return templates.TemplateResponse(
        request,
        "partials/generate_result.html",
        {"status": "processing", "job_id": job_id, "progress": 0, "mode": "ai"},
    )


async def _render_ai_banner(
    job_id: str, svg_string: str, width: int, height: int,
    render_instruction, nano_client, creative_direction: str | None = None,
    custom_ref_bytes: bytes | None = None, mode: str = "manual",
) -> None:
    """Render SVG to PNG as reference, then send to AI for enhancement."""
    job = _jobs[job_id]
    try:
        # Step 1: Render SVG → PNG
        job["progress"] = 10
        svg_for_render = await asyncio.to_thread(_embed_local_images, svg_string)
        png_bytes = await asyncio.to_thread(_svg_to_png, svg_for_render, width, height)

        svg_filename = f"{job_id}_svg.png"
        with open(os.path.join(OUTPUT_DIR, svg_filename), "wb") as f:
            f.write(png_bytes)
        job["file_url"] = f"/static/generated/{svg_filename}"
        job["progress"] = 20

        # Step 2: Send to AI — use original uploaded image for custom templates
        reference_bytes = custom_ref_bytes if custom_ref_bytes else png_bytes
        ai_job_id = await nano_client.generate_from_reference(
            reference_image_bytes=reference_bytes,
            instruction=render_instruction.model_dump(),
            user_prompt=creative_direction,
            mode=mode,
        )

        # Step 3: Poll AI generation
        while True:
            status = await nano_client.get_status(ai_job_id)
            job["progress"] = 20 + min(int(status.get("progress", 0) * 0.7), 70)
            if status["status"] == "completed":
                break
            if status["status"] == "failed":
                job["status"] = "failed"
                job["error"] = status.get("error", "AI generation failed")
                return
            await asyncio.sleep(0.5)

        # Step 4: Save AI result
        ai_bytes = await nano_client.get_result(ai_job_id)
        if not ai_bytes:
            job["status"] = "failed"
            job["error"] = "No image data returned from AI"
            return

        ai_filename = f"{job_id}_ai.png"
        with open(os.path.join(OUTPUT_DIR, ai_filename), "wb") as f:
            f.write(ai_bytes)

        job["ai_file_url"] = f"/static/generated/{ai_filename}"
        job["progress"] = 100
        job["status"] = "completed"

    except Exception as exc:
        logger.error("AI banner generation failed for job %s: %s", job_id, exc)
        job["status"] = "failed"
        job["error"] = str(exc)
        job["progress"] = 0




def _hex_to_rgba(hex_color: str) -> tuple[int, int, int, int]:
    """Convert hex color to RGBA tuple."""
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) == 6:
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), 255)
    if len(h) == 8:
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), int(h[6:8], 16))
    return (255, 255, 255, 255)


@router.get("/svg/{pattern_id}")
async def export_svg(request: Request, pattern_id: str):
    """Export the current banner as an SVG file with editable text."""
    from fastapi.responses import Response

    template_service = request.app.state.template_service
    svg_renderer = request.app.state.svg_renderer
    template = template_service.get_template(pattern_id)
    slot_values = request.session.get(f"slots_{pattern_id}", {})

    # Apply design overrides
    design_overrides = slot_values.get("_design")
    if isinstance(design_overrides, dict) and design_overrides.get("background_value"):
        template = template.model_copy(deep=True)
        template.design.background_value = design_overrides["background_value"]

    # embed_images=True converts all local /static/… hrefs to Base64 data URIs,
    # producing a fully self-contained SVG that opens in Adobe Illustrator offline.
    svg_string = svg_renderer.render(template, slot_values, embed_images=True)

    # Re-inject explicit width/height for Illustrator / print-ready exports.
    # The renderer omits them so the web preview SVG scales responsively, but
    # design tools require absolute pixel dimensions to interpret the canvas size.
    w, h = template.meta.width, template.meta.height
    svg_string = svg_string.replace("<svg ", f'<svg width="{w}" height="{h}" ', 1)

    # Duplicate href as xlink:href on every <image> element so Adobe Illustrator
    # (which ignores plain HTML5 href) can locate and render the image data.
    import re
    svg_string = re.sub(
        r'(<image[^>]*?)\bhref="([^"]+)"',
        r'\1 href="\2" xlink:href="\2"',
        svg_string,
    )

    return Response(
        content=svg_string.encode("utf-8"),
        media_type="image/svg+xml",
        headers={"Content-Disposition": f'attachment; filename="{pattern_id}.svg"'},
    )


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
            "pattern_id": job.get("pattern_id", ""),
            "progress": job["progress"],
            "file_url": job.get("file_url"),
            "ai_file_url": job.get("ai_file_url"),
            "mode": job.get("mode", "svg"),
            "error": job.get("error"),
        },
    )
