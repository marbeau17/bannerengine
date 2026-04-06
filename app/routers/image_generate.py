"""Image generation routes - generate images from prompts for individual slots."""

from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app.core.exceptions import ValidationError

logger = logging.getLogger("banner_engine")
# Force uvicorn reload to pick up rembg[cpu] installation

router = APIRouter(prefix="/api/image-generate", tags=["image-generate"])


@router.post("/{pattern_id}/{slot_id}", status_code=202)
async def start_image_generation(request: Request, pattern_id: str, slot_id: str):
    """Start AI image generation for a specific slot.

    Accepts form data with a 'prompt' field describing the desired image.
    Returns 202 Accepted with a job_id for progress tracking.
    """
    template_service = request.app.state.template_service
    template = template_service.get_template(pattern_id)

    # Find the target slot
    slot = next((s for s in template.slots if s.id == slot_id), None)
    if slot is None:
        raise ValidationError(
            message=f"Slot '{slot_id}' not found in template '{pattern_id}'.",
            errors=[f"Unknown slot: {slot_id}"],
        )

    # Validate slot type supports image generation
    if slot.type.value not in ("image", "image_or_text"):
        raise ValidationError(
            message=f"Slot '{slot_id}' does not support image generation.",
            errors=[f"Slot type '{slot.type.value}' cannot generate images"],
        )

    # Parse form data
    form_data = await request.form()
    prompt = form_data.get("prompt", "")

    if not prompt or not str(prompt).strip():
        raise ValidationError(
            message="Prompt is required for image generation.",
            errors=["Empty prompt"],
        )

    prompt = str(prompt).strip()

    # Calculate slot dimensions in pixels for generation
    width = int(slot.width / 100.0 * template.meta.width)
    height = int(slot.height / 100.0 * template.meta.height)
    # Ensure minimum dimensions
    width = max(width, 256)
    height = max(height, 256)

    # Auto-append image requirements to prompt
    extra = [f"\n\nImage requirements: {width}x{height} pixels."]
    if slot.format_hint:
        extra.append(f"Format: {slot.format_hint}.")
    # Removed slot.description from Context to prevent prompt contamination bias
    # If the user types "cardboard boxes" we don't want "Context: stationery" leaking in.
    prompt = prompt + " ".join(extra)

    # Start generation
    image_gen_service = request.app.state.image_generation_service
    job_id = await image_gen_service.generate_for_slot(
        prompt=prompt,
        pattern_id=pattern_id,
        slot_id=slot_id,
        width=width,
        height=height,
    )

    # Save prompt to session
    session_slots = request.session.get(f"slots_{pattern_id}", {})
    if slot_id not in session_slots or not isinstance(session_slots.get(slot_id), dict):
        session_slots[slot_id] = {}
    if isinstance(session_slots[slot_id], str):
        session_slots[slot_id] = {"source_url": session_slots[slot_id]}
    session_slots[slot_id]["prompt"] = prompt
    session_slots[slot_id]["generation_job_id"] = job_id
    request.session[f"slots_{pattern_id}"] = session_slots

    return JSONResponse(
        status_code=202,
        content={
            "job_id": job_id,
            "status": "queued",
            "message": "Image generation started.",
        },
    )


@router.get("/status/{job_id}")
async def image_generation_status(request: Request, job_id: str):
    """SSE endpoint for image generation progress.

    Streams Server-Sent Events with progress updates until completion.
    """
    image_gen_service = request.app.state.image_generation_service
    status = await image_gen_service.get_job_status(job_id)

    if status["status"] == "not_found":
        return JSONResponse(
            status_code=404,
            content={"detail": f"Job not found: {job_id}"},
        )

    async def event_stream():
        while True:
            status = await image_gen_service.get_job_status(job_id)
            event_data = json.dumps(status)
            yield f"data: {event_data}\n\n"

            if status["status"] in ("completed", "failed"):
                break

            await asyncio.sleep(0.5)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/apply/{pattern_id}/{slot_id}")
async def apply_generated_image(request: Request, pattern_id: str, slot_id: str):
    """Apply a generated image to a slot.

    After generation completes, this endpoint updates the slot value
    with the generated image URL and re-renders the preview.
    """
    template_service = request.app.state.template_service
    svg_renderer = request.app.state.svg_renderer
    template = template_service.get_template(pattern_id)

    form_data = await request.form()
    image_url = form_data.get("image_url", "")
    prompt = form_data.get("prompt", "")
    transparent_bg = str(form_data.get("transparent_bg", "false")).lower() == "true"

    if not image_url:
        raise ValidationError(
            message="Image URL is required.",
            errors=["Missing image_url"],
        )

    final_url = str(image_url)

    # Background removal via rembg when the 透明化 toggle is active
    rembg_failed = False
    if transparent_bg:
        try:
            import asyncio as _asyncio
            import io as _io
            import os as _os
            import traceback as _tb
            from rembg import remove as _rembg_remove
            from PIL import Image as _PILImage

            logger.info("rembg: starting background removal for slot %s (url=%s)", slot_id, final_url)

            # Load source image bytes
            img_bytes: bytes | None = None
            if final_url.startswith("/static/"):
                local_path = final_url.lstrip("/")
                if _os.path.exists(local_path):
                    with open(local_path, "rb") as f:
                        img_bytes = f.read()
                    logger.info("rembg: loaded %d bytes from local path %s", len(img_bytes), local_path)
                else:
                    logger.error("rembg: local file not found: %s", local_path)
            if img_bytes is None:
                import httpx as _httpx
                logger.info("rembg: fetching image over HTTP from %s", final_url)
                async with _httpx.AsyncClient() as client:
                    resp = await client.get(final_url, timeout=15)
                    img_bytes = resp.content
                    logger.info("rembg: fetched %d bytes (HTTP %s)", len(img_bytes), resp.status_code)

            # Remove background (runs synchronously in a thread to avoid blocking the event loop)
            def _do_remove(data: bytes) -> bytes:
                img_in = _PILImage.open(_io.BytesIO(data)).convert("RGBA")
                result = _rembg_remove(img_in)
                buf = _io.BytesIO()
                result.save(buf, format="PNG")
                return buf.getvalue()

            removed_bytes = await _asyncio.to_thread(_do_remove, img_bytes)
            logger.info("rembg: background removal produced %d bytes", len(removed_bytes))

            # Save the processed PNG alongside other generated assets
            from app.routers.generate import OUTPUT_DIR as _OUT_DIR
            import uuid as _uuid
            out_filename = f"rembg_{_uuid.uuid4().hex[:12]}.png"
            out_path = _os.path.join(_OUT_DIR, out_filename)
            with open(out_path, "wb") as f:
                f.write(removed_bytes)
            final_url = f"/static/generated/{out_filename}"
            logger.info("rembg: saved transparent PNG → %s", final_url)

        except ImportError:
            rembg_failed = True
            logger.error(
                "rembg ImportError for slot %s — rembg or onnxruntime not available in this Python environment. "
                "Run: pip install 'rembg[cpu]' in the active venv, then restart uvicorn.",
                slot_id,
            )
        except Exception as exc:
            rembg_failed = True
            import traceback as _tb
            logger.error(
                "rembg failed for slot %s: %s\n%s",
                slot_id,
                exc,
                _tb.format_exc(),
            )

    # Update session
    session_slots = request.session.get(f"slots_{pattern_id}", {})
    session_slots[slot_id] = {
        "source_url": final_url,
        "prompt": str(prompt),
        "fit": "cover",
        "transparent_bg": transparent_bg,
    }
    request.session[f"slots_{pattern_id}"] = session_slots

    # Re-render preview
    from fastapi.templating import Jinja2Templates
    templates = Jinja2Templates(directory="app/templates")

    svg_markup = svg_renderer.render(template, session_slots)

    response = templates.TemplateResponse(
        request,
        "partials/preview_canvas.html",
        {
            "template": template,
            "pattern_id": pattern_id,
            "svg_markup": svg_markup,
        },
    )
    # Let the frontend know if background removal failed so it can warn the user
    if rembg_failed:
        response.headers["X-Rembg-Failed"] = "true"
    return response
