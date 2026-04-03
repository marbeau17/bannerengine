"""AI generation orchestration - auto-fill blank slots and blend into final banner."""

from __future__ import annotations

import asyncio
import logging
import os
import uuid

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

logger = logging.getLogger("banner_engine")

router = APIRouter(prefix="/api/ai-generation", tags=["ai_generation"])
templates = Jinja2Templates(directory="app/templates")

_jobs: dict[str, dict] = {}
_MAX_JOBS = 200
OUTPUT_DIR = os.path.join("static", "generated")
os.makedirs(OUTPUT_DIR, exist_ok=True)


def _evict_old_jobs() -> None:
    if len(_jobs) <= _MAX_JOBS:
        return
    removable = [jid for jid, j in _jobs.items() if j["status"] in ("completed", "failed")]
    for jid in removable[: len(_jobs) - _MAX_JOBS]:
        _jobs.pop(jid, None)


@router.post("/generate-remaining-and-blend/{pattern_id}", response_class=HTMLResponse)
async def generate_remaining_and_blend(request: Request, pattern_id: str):
    """Auto-fill blank slots with AI, composite the layout, then run a final AI blend pass.

    Pipeline:
      1. Detect unfilled slots (10%)
      2. Concurrently generate text/images for blank slots (10-50%)
      3. Render composite SVG → PNG (50-60%)
      4. AI image-to-image polish pass via NanoBanana (60-100%)
    """
    template_service = request.app.state.template_service
    svg_renderer = request.app.state.svg_renderer
    banner_service = request.app.state.banner_service
    nano_client = request.app.state.nano_banana_client
    image_gen_service = request.app.state.image_generation_service
    template = template_service.get_template(pattern_id)

    form = await request.form()
    global_prompt = str(form.get("global_prompt", "") or "").strip() or None

    # Parse per-slot locked values (Case A) and user-typed prompt guidelines (Case B)
    locked_slots: dict[str, str] = {}
    slot_prompts: dict[str, str] = {}
    for key, value in form.multi_items():
        if key.startswith("locked_") and not key.startswith("locked_image_"):
            slot_id = key[7:]
            locked_slots[slot_id] = str(value)
        elif key.startswith("prompt_"):
            slot_id = key[7:]
            slot_prompts[slot_id] = str(value)

    # Snapshot current session slot values (mutable copy for auto-fill)
    slot_values: dict = dict(request.session.get(f"slots_{pattern_id}", {}))

    _evict_old_jobs()
    job_id = str(uuid.uuid4())
    _jobs[job_id] = {
        "job_id": job_id,
        "pattern_id": pattern_id,
        "status": "processing",
        "progress": 0,
        "step": "パイプラインを開始中...",
        "file_url": None,
        "ai_file_url": None,
    }

    poll_url = f"/api/ai-generation/progress/{job_id}"

    asyncio.create_task(
        _run_blend_pipeline(
            job_id,
            request,
            pattern_id,
            template,
            slot_values,
            global_prompt,
            locked_slots,
            slot_prompts,
            svg_renderer,
            banner_service,
            nano_client,
            image_gen_service,
        )
    )

    return templates.TemplateResponse(
        request,
        "partials/generate_result.html",
        {
            "status": "processing",
            "job_id": job_id,
            "progress": 0,
            "mode": "ai",
            "poll_url": poll_url,
        },
    )


async def _generate_text_for_slot(
    nano_client, slot, global_prompt: str | None, guideline: str | None = None
) -> str:
    """Use Gemini to generate short copy text for a text or button slot.

    Prompt strategy (avoids the "Ramen & Pens" dummy-text bias):
    - Never passes slot.description or slot.default_label to the model —
      those fields contain template-specific dummy copy that biases the AI
      toward the wrong theme when the user switches subjects.
    - Uses only structural information: slot type and the user-supplied theme.
    - When a guideline is present (Case B), enforces it strictly so the model
      cannot hallucinate an entirely different message.

    Args:
        guideline: User-typed hint for this specific slot (Case B).
    """
    try:
        model = nano_client._get_model()
        max_chars = slot.max_chars or 50
        slot_type_label = slot.type.value  # "text", "button", "image_or_text"

        # Purely structural base — the theme comes from global_prompt alone.
        # Omitting slot.description prevents the "Ramen & Pens" bias.
        if global_prompt:
            base = (
                f"Generate copy text for a '{slot_type_label}' element "
                f"on a banner about: {global_prompt}."
            )
        else:
            base = f"Generate short banner copy text for a '{slot_type_label}' element."

        prompt_parts = [
            base,
            f"Maximum {max_chars} characters. Output ONLY the final text, no quotes or explanation.",
        ]

        if guideline:
            # Case B: strict enforcement — user intent must not be discarded.
            prompt_parts.insert(
                0,
                f"CRITICAL INSTRUCTION: The user's exact required message for this slot is: "
                f"'{guideline}'. You MUST use this as the core message. You may lightly polish "
                f"the phrasing to fit the banner theme, but do NOT hallucinate a different "
                f"message or ignore this instruction.",
            )

        response = await asyncio.to_thread(model.generate_content, "\n".join(prompt_parts))
        text = ""
        if response.parts:
            for part in response.parts:
                if hasattr(part, "text") and part.text:
                    text += part.text
        return text.strip()[:max_chars] or slot.default_label or slot.id
    except Exception as exc:
        logger.warning("Text generation for slot %s failed: %s", slot.id, exc)
        return slot.default_label or slot.id


async def _run_blend_pipeline(
    job_id: str,
    request: Request,
    pattern_id: str,
    template,
    slot_values: dict,
    global_prompt: str | None,
    locked_slots: dict[str, str],
    slot_prompts: dict[str, str],
    svg_renderer,
    banner_service,
    nano_client,
    image_gen_service,
) -> None:
    """Full pipeline: apply locks → auto-fill blanks → composite SVG → AI polish blend.

    Slot handling:
      Case A (locked_slots): user explicitly generated text — keep exactly as-is.
      Case B (slot_prompts): user typed a guideline but did not generate — use as AI hint.
      Case C (blank): nothing provided — AI invents freely.
    """
    from app.routers.generate import _embed_local_images, _svg_to_png

    job = _jobs[job_id]
    try:
        # Step 1: Apply locked slots (Case A) and detect what still needs filling (0–10%)
        job["progress"] = 5
        job["step"] = "空きスロットを検出中..."

        for slot_id, text in locked_slots.items():
            if text:
                existing = slot_values.get(slot_id, {})
                if not isinstance(existing, dict):
                    existing = {}
                existing["text"] = text
                existing["content"] = text
                slot_values[slot_id] = existing

        # Build tasks for slots that still need content
        # A slot is "filled" if it's in slot_values AND has meaningful content
        def _is_filled(slot_id: str) -> bool:
            val = slot_values.get(slot_id)
            if not val:
                return False
            if isinstance(val, str):
                return bool(val.strip())
            if isinstance(val, dict):
                return any(
                    bool(str(val.get(k, "")).strip())
                    for k in ("text", "content", "label", "source_url", "image_url")
                )
            return False

        blank_tasks: list[tuple[str, object]] = []
        for slot in template.slots:
            if _is_filled(slot.id):
                continue
            if slot.type.value in ("text", "button"):
                blank_tasks.append(("text", slot))
            elif slot.type.value in ("image", "image_or_text"):
                blank_tasks.append(("image", slot))

        job["progress"] = 10
        job["step"] = "ドラフトを生成中... (10%)"

        # Step 2: Concurrently fill remaining slots (10–50%)
        # Case B: guideline-driven; Case C: free invention
        if blank_tasks:
            canvas_w = template.meta.width
            canvas_h = template.meta.height

            async def fill_text(slot) -> tuple[str, dict | None]:
                guideline = slot_prompts.get(slot.id)  # None for Case C
                text = await _generate_text_for_slot(nano_client, slot, global_prompt, guideline=guideline)
                return slot.id, {"slot_type": "text", "text": text, "content": text}

            async def fill_image(slot) -> tuple[str, dict | None]:
                slot_desc = slot.description or slot.id
                img_prompt = f"{global_prompt + '. ' if global_prompt else ''}{slot_desc}"
                w = max(int(slot.width / 100 * canvas_w), 256)
                h = max(int(slot.height / 100 * canvas_h), 256)
                client_job_id = await image_gen_service.generate_for_slot(
                    prompt=img_prompt,
                    pattern_id=pattern_id,
                    slot_id=slot.id,
                    width=w,
                    height=h,
                )
                for _ in range(120):  # max 60s
                    status = await image_gen_service.get_job_status(client_job_id)
                    if status["status"] == "completed":
                        return slot.id, {
                            "slot_type": "image",
                            "source_url": status["image_url"],
                            "fit": "cover",
                        }
                    if status["status"] == "failed":
                        return slot.id, None
                    await asyncio.sleep(0.5)
                return slot.id, None

            coros = [
                fill_text(slot) if kind == "text" else fill_image(slot)
                for kind, slot in blank_tasks
            ]
            results = await asyncio.gather(*coros, return_exceptions=True)

            for result in results:
                if isinstance(result, Exception):
                    logger.warning("Slot auto-fill error: %s", result)
                    continue
                slot_id, value = result
                if value:
                    slot_values[slot_id] = value

        # Persist updated slots to session (covers locked + newly filled)
        request.session[f"slots_{pattern_id}"] = slot_values

        job["progress"] = 50
        job["step"] = "レイアウトを組み立て中... (50%)"

        # Step 3: Render composite SVG → PNG (50–60%)
        svg_string = svg_renderer.render(template, slot_values)
        svg_embedded = await asyncio.to_thread(_embed_local_images, svg_string)
        png_bytes = await asyncio.to_thread(
            _svg_to_png, svg_embedded, template.meta.width, template.meta.height
        )

        composite_filename = f"{job_id}_composite.png"
        with open(os.path.join(OUTPUT_DIR, composite_filename), "wb") as f:
            f.write(png_bytes)
        job["file_url"] = f"/static/generated/{composite_filename}"
        job["progress"] = 60
        job["step"] = "AIで仕上げ中... (60%)"

        # Step 4: AI polish blend via NanoBanana (60–100%)
        render_instruction = banner_service.create_render_instruction(pattern_id, slot_values)
        ai_job_id = await nano_client.generate_from_reference(
            reference_image_bytes=png_bytes,
            instruction=render_instruction.model_dump(),
            user_prompt=global_prompt,
            mode="ai",
        )

        while True:
            status = await nano_client.get_status(ai_job_id)
            job["progress"] = 60 + min(int(status.get("progress", 0) * 0.4), 39)
            if status["status"] == "completed":
                break
            if status["status"] == "failed":
                job["status"] = "failed"
                job["error"] = status.get("error", "AI blend failed")
                return
            await asyncio.sleep(0.5)

        ai_bytes = await nano_client.get_result(ai_job_id)
        if not ai_bytes:
            job["status"] = "failed"
            job["error"] = "AIから画像が返されませんでした"
            return

        ai_filename = f"{job_id}_ai.png"
        with open(os.path.join(OUTPUT_DIR, ai_filename), "wb") as f:
            f.write(ai_bytes)

        job["ai_file_url"] = f"/static/generated/{ai_filename}"
        job["progress"] = 100
        job["step"] = "完了"
        job["status"] = "completed"

    except Exception as exc:
        logger.error("AI blend pipeline failed for job %s: %s", job_id, exc)
        job["status"] = "failed"
        job["error"] = str(exc)
        job["progress"] = 0


@router.get("/progress/{job_id}", response_class=HTMLResponse)
async def blend_progress(request: Request, job_id: str):
    """Return the current blend pipeline status as an HTML partial for htmx polling."""
    if job_id not in _jobs:
        return templates.TemplateResponse(
            request,
            "partials/generate_result.html",
            {"status": "error", "error": f"Job not found: {job_id}"},
        )

    job = _jobs[job_id]
    poll_url = f"/api/ai-generation/progress/{job_id}"
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
            "mode": "ai",
            "poll_url": poll_url,
            "error": job.get("error"),
        },
    )


@router.post("/generate-slot-text/{pattern_id}/{slot_id}")
async def generate_slot_text(request: Request, pattern_id: str, slot_id: str):
    """Generate AI text copy for a single text or button slot and save it to the session.

    Returns JSON with the generated text. The caller is responsible for
    updating the preview (e.g. by PATCHing /api/slots/{pattern_id}/{slot_id}).
    """
    template_service = request.app.state.template_service
    nano_client = request.app.state.nano_banana_client
    template = template_service.get_template(pattern_id)

    slot = next((s for s in template.slots if s.id == slot_id), None)
    if slot is None:
        return JSONResponse(
            status_code=404,
            content={"error": f"Slot '{slot_id}' not found"},
        )

    if slot.type.value not in ("text", "button", "image_or_text"):
        return JSONResponse(
            status_code=400,
            content={"error": f"Slot type '{slot.type.value}' does not support text generation"},
        )

    form = await request.form()
    user_prompt = str(form.get("prompt", "") or "").strip() or None

    text = await _generate_text_for_slot(nano_client, slot, user_prompt)

    # Persist to session
    session_slots = dict(request.session.get(f"slots_{pattern_id}", {}))
    existing = session_slots.get(slot_id, {})
    if not isinstance(existing, dict):
        existing = {}
    existing["text"] = text
    existing["content"] = text
    existing["slot_type"] = slot.type.value
    session_slots[slot_id] = existing
    request.session[f"slots_{pattern_id}"] = session_slots

    return JSONResponse(content={"text": text, "slot_id": slot_id})
