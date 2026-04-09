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

# Appended to any image prompt where rembg=True to prevent edge-clipping artifacts.
_ANTI_CROP_CONSTRAINT = (
    "\nCRITICAL INSTRUCTION: The subject must be fully contained within the frame. "
    "Ensure wide negative space/margins around all sides of the object. "
    "DO NOT crop, clip, or cut off any part of the subject at the image borders. "
    "Center the entire object perfectly. "
    "The background MUST be a solid, uniform, bright green (#00FF00) color — like a chroma-key green screen. "
    "NO gradients, NO patterns, NO scenery — ONLY a flat bright green background behind the subject."
)


def _evict_old_jobs() -> None:
    if len(_jobs) <= _MAX_JOBS:
        return
    removable = [jid for jid, j in _jobs.items() if j["status"] in ("completed", "failed")]
    for jid in removable[: len(_jobs) - _MAX_JOBS]:
        _jobs.pop(jid, None)


def _safe_float(val, default: float = 0.0) -> float:
    """Convert a value to float, stripping '%', 'px', etc. that Gemini may add."""
    if val is None:
        return default
    s = str(val).strip().rstrip("%").rstrip("px").strip()
    try:
        return float(s)
    except (ValueError, TypeError):
        return default


@router.post("/generate-remaining-and-blend/{pattern_id}", response_class=HTMLResponse)
async def generate_remaining_and_blend(request: Request, pattern_id: str):
    """Native component generation pipeline (unified Phase 0-4).

    Phase 0: Auto-fill blank slots via Gemini.
    Phase 1: Gemini Art Director produces a per-layer manifest.
    Phase 2: Crop → image-to-image cleanup per flagged layer.
    Phase 3: Conditional rembg (alpha_matting) for transparency.
    Phase 4: Inject as _custom_layers; canvas refreshes natively.
    """
    template_service = request.app.state.template_service
    svg_renderer = request.app.state.svg_renderer
    nano_client = request.app.state.nano_banana_client
    image_gen_service = request.app.state.image_generation_service
    template = template_service.get_template(pattern_id)

    form = await request.form()
    global_prompt = str(form.get("global_prompt", "") or "").strip() or None

    locked_slots: dict[str, str] = {}
    slot_prompts: dict[str, str] = {}
    for key, value in form.multi_items():
        if key.startswith("locked_") and not key.startswith("locked_image_"):
            locked_slots[key[7:]] = str(value)
        elif key.startswith("prompt_"):
            slot_prompts[key[7:]] = str(value)

    slot_values: dict = dict(request.session.get(f"slots_{pattern_id}", {}))

    _evict_old_jobs()
    job_id = str(uuid.uuid4())
    _jobs[job_id] = {
        "job_id": job_id,
        "pattern_id": pattern_id,
        "status": "processing",
        "progress": 0,
        "step": "パイプラインを開始中...",
    }

    poll_url = f"/api/ai-generation/progress/{job_id}"

    asyncio.create_task(
        _run_native_pipeline(
            job_id, request, pattern_id, template, slot_values,
            global_prompt, locked_slots, slot_prompts,
            svg_renderer, nano_client, image_gen_service,
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


@router.post("/raster-inspire/{pattern_id}")
async def raster_inspire(request: Request, pattern_id: str):
    """Step 1 of the Visual Inspiration Pipeline.

    Generates a flat, uneditable PNG raster banner from a user prompt.
    Returns a job_id for polling via the existing image-generate status SSE.
    """
    template_service = request.app.state.template_service
    image_gen_service = request.app.state.image_generation_service
    template = template_service.get_template(pattern_id)

    form = await request.form()
    prompt = str(form.get("prompt", "")).strip()
    if not prompt:
        from fastapi.responses import JSONResponse as _JSONResponse
        return _JSONResponse({"error": "prompt required"}, status_code=422)

    # Force the raster inspiration image to be a pure visual scene with NO text,
    # so Gemini's subsequent analysis isn't distracted by hallucinated typography.
    prompt = prompt + (
        "\nCRITICAL: DO NOT GENERATE ANY WORDS, LETTERS, SIGNAGE, OR TEXT OF ANY KIND. "
        "Only generate physical objects, scenery, and colors."
    )

    width = template.meta.width
    height = template.meta.height

    job_id = await image_gen_service.generate_for_slot(
        prompt=prompt,
        pattern_id=pattern_id,
        slot_id="__raster_inspire__",
        width=width,
        height=height,
    )

    from fastapi.responses import JSONResponse as _JSONResponse
    return _JSONResponse({
        "job_id": job_id,
        "poll_url": f"/api/image-generate/status/{job_id}",
    })


@router.post("/layerize/{pattern_id}", response_class=HTMLResponse)
async def layerize(request: Request, pattern_id: str):
    """Step 2 of the Visual Inspiration Pipeline.

    Takes a reference_image_url (the flat raster from Step 1) and fires
    macro_autofill with Gemini Vision in multimodal mode, so the AI maps
    the reference image's aesthetic into the layered JSON template.
    """
    template_service = request.app.state.template_service
    svg_renderer = request.app.state.svg_renderer
    nano_client = request.app.state.nano_banana_client
    image_gen_service = request.app.state.image_generation_service
    template = template_service.get_template(pattern_id)

    form = await request.form()
    reference_image_url = str(form.get("reference_image_url", "")).strip()
    global_prompt = str(form.get("global_prompt", "") or "").strip() or None

    slot_values: dict = dict(request.session.get(f"slots_{pattern_id}", {}))

    _evict_old_jobs()
    job_id = str(uuid.uuid4())
    _jobs[job_id] = {
        "job_id": job_id,
        "pattern_id": pattern_id,
        "status": "processing",
        "progress": 0,
        "step": "ビジョンAIでレイヤー解析中...",
    }

    poll_url = f"/api/ai-generation/progress/{job_id}"

    asyncio.create_task(
        _run_native_pipeline(
            job_id, request, pattern_id, template, slot_values,
            global_prompt, {}, {},
            svg_renderer, nano_client, image_gen_service,
            reference_image_url=reference_image_url or None,
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


def _remove_background_alpha(image_bytes: bytes) -> bytes:
    """Strip solid backgrounds via rembg. Uses green-screen-aware approach."""
    import rembg
    from PIL import Image
    import io

    # Get original pixel count for validation
    orig_img = Image.open(io.BytesIO(image_bytes))
    total_pixels = orig_img.size[0] * orig_img.size[1]

    def _validate_output(result_bytes: bytes, label: str) -> bool:
        """Check that rembg kept enough visible pixels (at least 5% of image)."""
        try:
            out_img = Image.open(io.BytesIO(result_bytes)).convert("RGBA")
            alpha = out_img.split()[3]
            visible = sum(1 for p in alpha.getdata() if p > 30)
            pct = visible / total_pixels * 100
            logger.info("rembg %s: %d/%d visible pixels (%.1f%%)", label, visible, total_pixels, pct)
            return pct >= 0.5  # at least 0.5% of image should be the subject
        except Exception:
            return len(result_bytes) > 5000

    # Try 1: Default model without alpha_matting (most reliable)
    try:
        result = rembg.remove(image_bytes, alpha_matting=False)
        if result and _validate_output(result, "default"):
            return result
        logger.warning("rembg default removed too much, trying alpha_matting")
    except Exception as e:
        logger.warning("rembg default failed: %s", e)

    # Try 2: With alpha_matting (more aggressive edge detection)
    try:
        result = rembg.remove(image_bytes, alpha_matting=True)
        if result and _validate_output(result, "alpha_matting"):
            return result
        logger.warning("rembg alpha_matting also removed too much")
    except Exception as e:
        logger.warning("rembg alpha_matting failed: %s", e)

    # Try 3: Green screen approach — mask out the green channel manually
    logger.info("rembg: falling back to green-screen chroma key removal")
    try:
        import numpy as np
        img_array = np.array(orig_img.convert("RGB"))
        # Detect bright green pixels (chroma key)
        r, g, b = img_array[:,:,0], img_array[:,:,1], img_array[:,:,2]
        green_mask = (g > 150) & (g > r + 40) & (g > b + 40)
        # Create RGBA with green pixels made transparent
        rgba = np.dstack([img_array, np.full(img_array.shape[:2], 255, dtype=np.uint8)])
        rgba[green_mask, 3] = 0
        out_img = Image.fromarray(rgba, "RGBA")
        buf = io.BytesIO()
        out_img.save(buf, format="PNG")
        result = buf.getvalue()
        if _validate_output(result, "chroma_key"):
            return result
    except Exception as e:
        logger.warning("Chroma key fallback failed: %s", e)

    # Last resort: return original image unchanged
    logger.warning("All rembg methods failed, returning original image")
    return image_bytes


async def _run_native_pipeline(
    job_id: str,
    request: Request,
    pattern_id: str,
    template,
    slot_values: dict,
    global_prompt: str | None,
    locked_slots: dict[str, str],
    slot_prompts: dict[str, str],
    svg_renderer,
    nano_client,
    image_gen_service,
    reference_image_url: str | None = None,
) -> None:
    """Macro Auto-Fill pipeline.

    Phase 0  Auto-fill blank text/image slots via individual Gemini calls.
    Phase 1  Gemini Macro Orchestration: unified creative fill manifest
             (text copy, fill colors, SVG text_style filters, image prompts,
              background overrides).
    Phase 2  Apply design overrides (background color/gradient).
    Phase 3  Apply slot fills (text, colors, text_style, image prompts).
    Phase 4  Generate images for image slots via image_gen_service.
    Phase 5  Render final composite SVG → PNG for preview.

    Session writes happen in blend_progress (the polling handler) because
    FastAPI session middleware cannot persist changes from background tasks.
    """

    job = _jobs[job_id]
    try:
        width = template.meta.width
        height = template.meta.height

        # ── Phase 0: Auto-fill blank slots ────────────────────────────────────
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
        job["step"] = "スロットを生成中... (10%)"

        if blank_tasks:
            async def fill_text(slot) -> tuple[str, dict | None]:
                guideline = slot_prompts.get(slot.id)
                text = await _generate_text_for_slot(nano_client, slot, global_prompt, guideline=guideline)
                return slot.id, {"slot_type": "text", "text": text, "content": text}

            async def fill_image(slot) -> tuple[str, dict | None]:
                img_prompt = f"{global_prompt + '. ' if global_prompt else ''}{slot.description or slot.id}"
                w = max(int(slot.width / 100 * width), 256)
                h = max(int(slot.height / 100 * height), 256)
                cjid = await image_gen_service.generate_for_slot(
                    prompt=img_prompt, pattern_id=pattern_id,
                    slot_id=slot.id, width=w, height=h,
                )
                for _ in range(120):
                    st = await image_gen_service.get_job_status(cjid)
                    if st["status"] == "completed":
                        return slot.id, {"slot_type": "image", "source_url": st["image_url"], "fit": "cover"}
                    if st["status"] == "failed":
                        return slot.id, None
                    await asyncio.sleep(0.5)
                return slot.id, None

            fill_results = await asyncio.gather(
                *[fill_text(s) if k == "text" else fill_image(s) for k, s in blank_tasks],
                return_exceptions=True,
            )
            for res in fill_results:
                if isinstance(res, Exception):
                    logger.warning("Slot auto-fill error: %s", res)
                    continue
                sid, val = res
                if val:
                    slot_values[sid] = val

        # ── Phase 0.5: Silent Muse — pre-render layout raster for AI extraction ─
        # Generates a structural mockup from the template slot geometry, then feeds
        # the resulting image to Gemini so it extracts style rather than inventing
        # blindly. Only fires on the main "AIで仕上げる" path; layerize already
        # supplies its own user-provided reference image.
        muse_image_bytes: bytes | None = None
        if reference_image_url is None:
            try:
                job["step"] = "Museで構造ラスターを生成中..."
                logger.info("macro_autofill: Silent Muse — building layout manifest")

                muse_instruction: dict = {
                    "canvas": {
                        "width": width,
                        "height": height,
                        "background_color": (
                            template.design.primary_color
                            or template.design.background_value
                            or "#FFFFFF"
                        ),
                        "format": "png",
                    },
                    "layers": [],
                }

                for _ms in template.slots:
                    if _ms.id == "__background__":
                        continue
                    _px_x = (_ms.x / 100.0) * width
                    _px_y = (_ms.y / 100.0) * height
                    _px_w = (_ms.width / 100.0) * width
                    _px_h = (_ms.height / 100.0) * height
                    _label = (
                        slot_values.get(_ms.id, {}).get("text")
                        or _ms.default_label
                        or _ms.id
                    ) if isinstance(slot_values.get(_ms.id), dict) else (_ms.default_label or _ms.id)

                    if _ms.type.value in ("text", "image_or_text"):
                        muse_instruction["layers"].append({
                            "type": "text",
                            "position": {"x": _px_x, "y": _px_y},
                            "text": {
                                "content": str(_label),
                                "font_size": max(12, int(_px_h * 0.55)),
                                "color": "#000000",
                            },
                        })
                    elif _ms.type.value == "image":
                        muse_instruction["layers"].append({
                            "type": "image",
                            "position": {"x": _px_x, "y": _px_y},
                            "size": {"width": _px_w, "height": _px_h},
                        })
                    elif _ms.type.value == "button":
                        muse_instruction["layers"].append({
                            "type": "button",
                            "position": {"x": _px_x, "y": _px_y},
                            "size": {"width": _px_w, "height": _px_h},
                            "text": {"content": "Shop Now"},
                        })

                _muse_job_id = await nano_client.submit_render(
                    muse_instruction,
                    user_prompt=(
                        f"{global_prompt or 'High-end professional advertising banner'}. "
                        "The background should feature a distinct patterned texture (halftone, fabric, grain, or geometric field). "
                        "Foreground should have atmospheric lighting effects like bokeh or light flares, separate from the background pattern."
                    ),
                )

                # Poll up to 30 seconds (60 × 0.5s)
                for _ in range(60):
                    _muse_status = await nano_client.get_status(_muse_job_id)
                    if _muse_status["status"] == "completed":
                        muse_image_bytes = await nano_client.get_result(_muse_job_id)
                        if muse_image_bytes:
                            logger.info(
                                "macro_autofill: Silent Muse generated (%d bytes)", len(muse_image_bytes)
                            )
                        break
                    if _muse_status["status"] == "failed":
                        logger.warning(
                            "macro_autofill: Silent Muse generation failed: %s",
                            _muse_status.get("error"),
                        )
                        break
                    await asyncio.sleep(0.5)

            except Exception as _muse_exc:
                logger.warning("macro_autofill: Silent Muse error (degrading gracefully): %s", _muse_exc)
                muse_image_bytes = None

        # ── Phase 1: Gemini Macro Auto-Fill Orchestration ──────────────────────
        job["progress"] = 30
        job["step"] = "Geminiでクリエイティブ設計中..."

        model = nano_client._get_model()

        layer_ctx_lines = []
        for slot in template.slots:
            val = slot_values.get(slot.id, {})
            if isinstance(val, dict) and val.get("_hidden"):
                continue
            # NOTE: We intentionally do NOT pass slot content/text to Gemini here.
            # Template dummy text (e.g. "Stationery Sale") infects the AI's creative
            # decisions and causes text hallucination in generated images. The AI must
            # work from geometry + type info only, never from template placeholder copy.
            font_hint = (
                f", font_size_guideline={slot.font_size_guideline}"
                if getattr(slot, "font_size_guideline", None)
                else ""
            )
            layer_ctx_lines.append(
                f"  id={slot.id}, type={slot.type.value}, "
                f"x={slot.x:.1f}%, y={slot.y:.1f}%, w={slot.width:.1f}%, h={slot.height:.1f}%, "
                f"max_chars={slot.max_chars or 50}{font_hint}"
            )
        layer_ctx = "\n".join(layer_ctx_lines) or "  (no slots)"

        bg_type = template.design.background_type or "solid"
        bg_value = template.design.background_value or template.design.primary_color or "#FFFFFF"

        # Detect layerize mode — changes prompt behavior to demand faithful replication
        _is_layerize = reference_image_url is not None

        orchestrator_prompt = (
            f"You are the AI Art Director for a {width}x{height}px banner.\n"
            f"User creative theme: \"{global_prompt or 'artistic enhancement'}\"\n"
            f"Current background: type={bg_type}, value={bg_value}\n\n"
            f"Template slots (PAY STRICT ATTENTION TO w/width AND h/height; use font_size_guideline as your px baseline for font_size):\n{layer_ctx}\n\n"
            "SPECIAL SLOT — __background__ (type=background, x=0,y=0,w=100,h=100):\n"
            "  This is a native full-canvas base background slot. Set it via the 'design' section.\n"
            "  CRITICAL: The base background is your ONLY place for repeating patterns, textures,\n"
            "  fabric weaves, halftone effects, watercolor washes, and solid gradient fields.\n"
            "  ALL foundational visual textures MUST go in background_image_prompt.\n"
            "  If the banner has a distinct main subject (product, person, device), use background_type='solid'\n"
            "  or 'gradient' to avoid subject duplication. Use background_type='image' only for pure abstract\n"
            "  texture/pattern scenes (halftone, fabric, paper grain, geometric field) with NO subject.\n"
            "  background_image_prompt must NEVER mention the product or subject.\n\n"
            "Your job: Design a COMPLETE, cohesive creative fill for this banner.\n\n"
            + (
            # Layerize mode: hide only what's NOT in the reference
            "── REFERENCE-DRIVEN LAYER MANAGEMENT ──\n"
            "You MUST map the reference image to template slots. For each template slot:\n"
            "  - If the reference image has a corresponding element → FILL the slot with matching content.\n"
            "  - If the reference image has NO corresponding element → HIDE the slot with {\"_hidden\": true}.\n"
            "  - If the reference image has elements with NO matching slot → spawn them as extra_layers.\n"
            "Do NOT add or remove layers based on aesthetic preference. Follow the reference EXACTLY.\n\n"
            if _is_layerize else
            # Normal creative mode: full creative freedom
            "── CREATIVE FREEDOM — LAYER DELETION ENCOURAGED ──\n"
            "You are NOT obligated to use every template slot. Templates are suggestions, not mandates.\n"
            "If a slot does not serve the design, HIDE IT. Output {\"_hidden\": true} for that slot.\n"
            "Fewer, stronger elements always beat cluttered designs that fill every slot.\n"
            "Examples of when to hide slots:\n"
            "  - A minimal poster-style design only needs a headline + product. Hide the subheadline and price.\n"
            "  - A CTA button doesn't fit the aesthetic. Hide it.\n"
            "  - Two text slots say similar things. Hide the redundant one.\n"
            "Conversely, if the design needs elements the template doesn't have, SPAWN them via extra_layers.\n"
            "You have FULL creative authority over what stays and what goes.\n\n"
            )
            + "Output a JSON object with these sections:\n\n"
            "1. \"design\" — global background:\n"
            "   - \"background_type\": \"image\" (PREFERRED), \"solid\", or \"gradient\"\n"
            "   - \"background_value\": hex color or \"#hex1,#hex2\"\n"
            "   - \"background_image_prompt\": (IF image) Write a base prompt here. NO PRODUCTS ALLOWED in this prompt.\n\n"
            "2. \"slots\" — for EACH slot id, an object:\n"
            "   ALL slot types accept these optional structural override keys (see STRUCTURAL OVERRIDE PROTOCOL below):\n"
            "     - \"x\": float 0–100 — override left edge %\n"
            "     - \"y\": float 0–100 — override top edge %\n"
            "     - \"width\": float 0–100 — override width %\n"
            "     - \"height\": float 0–100 — override height %\n"
            "   *** \"_hidden\": true — ENCOURAGED. Use this to remove any slot that does not serve the design. ***\n"
            "   A clean design with 3 well-placed elements is better than 6 cramped ones.\n"
            "   For text slots:\n"
            "     - \"text\": Catchy copy. VERY IMPORTANT: Before writing, assess the slot's w% and h% coordinates. "
            "Text must physically fit inside those boundaries. Keep copy extremely concise for narrow slots (w < 30%). "
            "Inject literal '\\n' characters to force line breaks and prevent horizontal overflow. "
            "Do NOT exceed the vertical limit — fewer lines are better than overflowing.\n"
            "     - \"fill_color\": *** LEGIBILITY FIRST — THIS IS NON-NEGOTIABLE ***\n"
            "         Mentally evaluate the luminance of your background (from background_image_prompt or background_value).\n"
            "         DARK backgrounds (night sky, forest, navy, charcoal, deep colors) → text fill MUST be WHITE (#ffffff) or a very pale tint (e.g. #f0f0f0, #fffde7).\n"
            "         LIGHT backgrounds (white, cream, light pastel, bright colors) → text fill MUST be BLACK (#000000) or very dark (e.g. #1a1a1a, #212121).\n"
            "         MID-TONE or PATTERNED backgrounds → default to WHITE text + a protective text_style effect (see below).\n"
            "         NEVER choose a fill_color that shares the same hue family as the background without adding a text_style shield.\n"
            "     - \"font_size\": number in px\n"
            "     - \"font_weight\": \"normal\"|\"bold\"|\"900\"\n"
            "     - \"opacity\": 0.0-1.0\n"
            "     - \"text_style\": SVG filter effect. REQUIRED when background is complex, patterned, or same hue as text. Fields:\n"
            "         effect_type: \"neon_glow\" | \"drop_shadow\" | \"outline_stroke\" | \"metallic\" | \"outline_and_shadow\"\n"
            "         effect_color: hex color for the stroke/glow (e.g. white stroke, neon color)\n"
            "         font_fill: hex override for the text fill color itself\n"
            "         shadow_blur: blur radius in px (0–30). Controls softness of glow or shadow (default 1).\n"
            "         shadow_dx: X offset for drop_shadow / outline_and_shadow (-20 to 20, default 0).\n"
            "         shadow_dy: Y offset for drop_shadow / outline_and_shadow (-20 to 20, default 1).\n"
            "         shadow_opacity: shadow opacity 0.0–1.0. Default 0.48.\n"
            "         shadow_color: shadow flood color for outline_and_shadow (e.g. #000000). Separate from effect_color.\n"
            "         stroke_width: outline thickness for outline_stroke / outline_and_shadow in px (1–10, default 2).\n"
            "       *** STACKING: outline_and_shadow ***\n"
            "       outline_and_shadow is the MOST POWERFUL effect — it renders a thick colored stroke AND a cast drop shadow simultaneously.\n"
            "       Use effect_color for the stroke color, shadow_color for the shadow color.\n"
            "       Example: white outline + black shadow: {effect_type:outline_and_shadow, effect_color:#ffffff, stroke_width:3, shadow_color:#000000, shadow_dx:0, shadow_dy:1, shadow_blur:1, shadow_opacity:0.48}\n"
            "       *** DO NOT BE CONSERVATIVE — MANDATE FOR HEADLINES ***\n"
            "       For hero titles, main headlines, and key text slots: you are STRONGLY ENCOURAGED to use\n"
            "       `outline_and_shadow` or `metallic` to create pop-art, high-impact, or punchy aesthetics.\n"
            "       Plain unstyled text is amateurish. Use SVG layer effects aggressively to create visual hierarchy.\n"
            "       Use `neon_glow` for cyberpunk/futuristic. Use `outline_and_shadow` for pop-art/retro/bold.\n"
            "       Use `metallic` for luxury/premium. Use `drop_shadow` for clean/modern.\n"
            "       *** MONOCHROMATIC / LOW-CONTRAST THEME RULE ***\n"
            "       If you want to use a thematic text color that shares the hue of the background (e.g. green text on a green forest image),\n"
            "       you are REQUIRED to protect legibility via text_style. You MUST choose one of:\n"
            "         A) outline_and_shadow with high-contrast stroke + shadow (BEST OPTION)\n"
            "         B) A THICK outline_stroke in a high-contrast color (stroke_width 4-6)\n"
            "         C) An aggressive drop_shadow (shadow_opacity 0.85+, shadow_blur 4+)\n"
            "         D) A neon_glow with a strongly contrasting effect_color\n"
            "       Failing to protect low-contrast text is a critical design error.\n"
            "       Examples:\n"
            "         Dark bg, white text, clean: fill_color:#ffffff (no text_style needed)\n"
            "         Pop-art headline: {effect_type:outline_and_shadow, effect_color:#ffffff, stroke_width:3, shadow_color:#000000, shadow_dx:0, shadow_dy:1, shadow_blur:1, shadow_opacity:0.48}\n"
            "         Retro yellow title: {effect_type:outline_and_shadow, effect_color:#000000, stroke_width:2, shadow_color:#8B0000, shadow_dx:0, shadow_dy:1, shadow_blur:1, shadow_opacity:0.48}\n"
            "         Neon cyberpunk: {effect_type:neon_glow, effect_color:#00fff0, shadow_blur:18}\n"
            "         Luxury metallic: {effect_type:metallic, effect_color:#d4af37, shadow_blur:2}\n"
            "         Monochromatic shield: fill_color:#00e676, {effect_type:outline_and_shadow, effect_color:#ffffff, stroke_width:4, shadow_color:#000000, shadow_dx:0, shadow_dy:1, shadow_blur:1, shadow_opacity:0.48}\n"
            "   For button slots:\n"
            "     - \"text\": button label. STRICT RULE: Button copy MUST be 1-3 words maximum. "
            "Button bounding boxes are small — verbose text will overflow and look broken. Examples: 'Shop Now', 'Get Started', '今すぐ購入'.\n"
            "     - \"bg_color\": hex for fallback button background\n"
            "     - \"text_color\": hex for button text. CONTRAST RULE: bg_color and text_color MUST be high-contrast opposites. "
            "Dark bg_color → light/white text_color. Light bg_color → dark/black text_color. Never use similar hues.\n"
            "     - \"bg_image_prompt\": (Optional) PROMPT TO RASTERIZE THE BUTTON BACKGROUND.\n"
            "       STRICT RULE: Focus on ultra-modern 2026 Japanese web aesthetics. Do NOT generate outdated 1990s/2000s glossy, heavily beveled buttons.\n"
            "       Use sleek solid minimalism, soft 100% opaque fluid gradients, ultra-premium flat UI, or opaque modern neumorphism.\n"
            "       CRITICAL REDUNDANCY: The button MUST be fully solid and opaque. DO NOT use glassmorphism, frosted glass, or translucent effects, as the automated background remover will delete the button entirely.\n"
            "       It MUST be perfectly orthographic (directly facing the camera, zero perspective) and fill the image frame edge-to-edge.\n"
            "       NO 3D floating buttons. NO drop shadows that leave empty margins.\n"
            "       Example: 'Ultra-modern sleek premium UI button, solid opaque pastel fluid gradient, bold clean flat design, 2026 Japanese web aesthetic, perfectly edge-to-edge orthographic view'.\n"
            "       NEVER use this for realistic scenes, illustrations, abstract blobs, or decorative art.\n"
            "       (If provided, we will rasterize and rembg the result.)\n"
            "   For image slots (product/subject photos):\n"
            "     - \"image_prompt\": DETAILED generation prompt — MUST include art style, composition,\n"
            "       specific elements, mood/lighting, and background description. Vague prompts produce bad images.\n"
            + (
            "     - \"rembg\": false (DEFAULT for layerize — only true when subject needs transparency over colored bg)\n"
            if _is_layerize else
            "     - \"rembg\": true (ALWAYS true for product images)\n"
            )
            + "     - \"gen_bg_color\": contrasting hex for generation background (e.g., #00AA00 for white objects)\n"
            "   For shape slots:\n"
            "     - \"fill_color\": hex matching theme\n\n"

            "3. \"extra_layers\" — new decorative layers to inject:\n"
            "   [{\"type\": \"rect\"|\"circle\"|\"image\", \"x\": %, \"y\": %, \"width\": %, \"height\": %, "
            "\"fill\": \"#hex\", \"opacity\": 0.0-1.0, \"label\": \"...\", \"image_prompt\": \"...\", "
            "\"rembg\": true|false, "
            "\"blend_mode\": \"normal\"|\"multiply\"|\"screen\"|\"overlay\"}]\n"
            "   Use rembg=true for cutout shapes (sakura branches, stickers, etc.).\n"
            "   Use blend_mode='multiply' or 'screen' for texture overlays, smoke, steam, bokeh, or sparkle effects.\n"
            "   IMPORTANT: If you want smoke, steam, or fire around a product, you MUST spawn it here as a separate extra_layer.\n"
            "   For smoke/steam, ALWAYS set rembg=false and brilliantly center the effect with empty black/white margins so it does not unnaturally cut off at the edges.\n"
            "   BACKGROUND COLOR RULE FOR BLEND MODES: When blend_mode is 'screen', the image_prompt MUST specify 'isolated on a pure BLACK background' (screen blends black to transparent). When blend_mode is 'multiply', specify 'isolated on a pure WHITE background'. NEVER use the wrong background color for the blend mode — this causes the entire layer to go opaque.\n"
            + (
            # In layerize mode: ambient FX only if the reference image has them
            "   *** FOREGROUND AMBIENT FX — REFERENCE-DRIVEN ***\n"
            "   ONLY add ambient FX extra_layers if the REFERENCE IMAGE clearly shows atmospheric effects\n"
            "   (bokeh, light flares, steam, particles, haze, lens flare, etc.).\n"
            "   If the reference image is clean, minimal, or has a plain/white background, do NOT add\n"
            "   any ambient FX layers. Faithfulness to the reference is MORE important than adding effects.\n"
            "   If the reference DOES show atmospheric effects, replicate them:\n"
            "     - type: \"image\", x/y/width/height matching where the effect appears in the reference\n"
            "     - opacity: match the visual intensity from the reference\n"
            "     - blend_mode: \"screen\" (for lighting) or \"overlay\" (for haze)\n"
            "     - image_prompt: describe the SPECIFIC effect you see in the reference image\n"
            "     - Z-ORDER STRICT RULE: You MUST calculate the layer_order perfectly! If it is steam or smoke coming off the product, place its ID IN FRONT of the product image (closer to index 0), but BEHIND text layers.\n\n"
            if _is_layerize else
            # Normal creative mode: contextual ambient FX
            "   *** AESTHETIC MANDATE — CONTEXTUAL AMBIENT FX ***\n"
            "   MANDATORY REQUIREMENT: You MUST ALWAYS generate 2 to 3 ambient FX extra_layers to perfectly sandwich the product and elevate visual depth.\n"
            "   Do NOT just make one generic layer. Think structurally about the product and scene:\n"
            "   0. DECORATIVE PATTERN TEXTURE (MANDATORY — always generate this):\n"
            "      - PURPOSE: A subtle repeating pattern or texture overlay that adds visual richness to the background area. Think: geometric shapes, dots, lines, abstract motifs, thematic icons (e.g. tiny stationery icons for a stationery sale, small food icons for a food banner).\n"
            "      - Z-ORDER: Place this DIRECTLY ABOVE __background__ (and above the background image if present), but BELOW everything else. It should be the second-from-bottom layer in layer_order.\n"
            "      - Size: FULL CANVAS coverage (x: 0, y: 0, width: 100, height: 100).\n"
            "      - blend_mode: 'multiply' (for dark patterns on light bg) or 'overlay' (for subtle texture on any bg).\n"
            "      - opacity: 0.15 to 0.40 — subtle, not overpowering. The pattern should enhance, not distract.\n"
            "      - image_prompt: Describe a seamless decorative pattern on pure WHITE background (for multiply blend). Examples:\n"
            "        * 'seamless repeating geometric diamond pattern, thin elegant lines, monochrome dark gray on pure white background'\n"
            "        * 'subtle scattered tiny stationery icons pattern (pencils, rulers, erasers), line art style, dark gray on pure white background'\n"
            "        * 'delicate Japanese wave pattern (seigaiha), thin lines, dark navy on pure white background'\n"
            "      - rembg: false (the blend mode handles transparency).\n"
            "      - This layer makes the design look polished and print-ready when exported as SVG.\n"
            "   1. BACKGROUND AMBIENT FX (Light Flares / Glows / Bokeh):\n"
            "      - Z-ORDER: Place this ABOVE the pattern texture but BELOW the product image.\n"
            "      - Size: Usually full canvas coverage (x: 0, y: 0, w: 100, h: 100).\n"
            "      - blend_mode: 'screen' or 'overlay'.\n"
            "      - Example: 'cinematic bokeh light blobs, warm golden tones on black background'.\n"
            "   2. FOREGROUND VOLUMETRIC FX (Smoke / Steam / Dynamic Particles):\n"
            "      - If the product is hot food, you MUST add 'rising hot white steam on black'. If it's a dynamic/sport item, add 'action dust particles on black'.\n"
            "      - Z-ORDER: This layer MUST be strictly placed IN FRONT of the product image (closer to index 0) but BEHIND text slots in layer_order.\n"
            "      - SIZE & POSITION: Do NOT just make it full canvas! Size and position this layer (x, y, width, height) perfectly contextualized over the product where the steam/particles should emanate from!\n"
            "      - blend_mode: 'screen' (for white steam/light/sparks) or 'multiply' (for dark smoke/shadows).\n\n"
            )
            + "4. \"layer_order\" — VERY IMPORTANT: A flat array of strings in FRONT-TO-BACK order (Photoshop layer panel convention).\n"
            "   - Index 0 = topmost layer (drawn last, appears in front).\n"
            "   - Last element = \"__background__\" (drawn first, always at the back).\n"
            "   - Include EVERY slot ID from Template slots and any extra layers.\n"
            "   - Extra layers use 0-indexed IDs: \"ai_extra_0\", \"ai_extra_1\", etc.\n"
            "   - Example: [\"cta_button\", \"headline\", \"ai_extra_0\", \"main_image\", \"bg_shape\", \"__background__\"]\n\n"

            "── STRUCTURAL OVERRIDE PROTOCOL ──\n"
            "You have permission to BREAK the template's default layout. If you are layerizing a reference image\n"
            "and a slot's default coordinates do not match the physical layout shown in the image, you MUST output\n"
            "new float percentage values to correct them:\n"
            "  - \"x\": new left edge (0–100%)\n"
            "  - \"y\": new top edge (0–100%)\n"
            "  - \"width\": new width (0–100%)\n"
            "  - \"height\": new height (0–100%)\n"
            "These override the template XML and reposition the slot on the canvas in real time.\n"
            "If a template slot has NO corresponding element in the reference image (it is not needed),\n"
            "output \"_hidden\": true inside that slot's object to destroy it from the render.\n"
            "If the image contains elements that do not map to any template slot, spawn them via extra_layers.\n"
            "Example: if a headline is at top in the image but the template places it at the bottom,\n"
            "output {\"x\": 5, \"y\": 3, \"width\": 90, \"height\": 18, \"text\": \"...\", ...} for that slot.\n\n"

            "── TYPOGRAPHICAL PARSING PROTOCOL ──\n"
            "Before mapping any text from a reference image, classify the typography:\n"
            "  A) STANDARD TYPOGRAPHY: clean, legible letters (serif, sans-serif, script, handwritten but readable).\n"
            "     → Map as a normal text slot. Use fill_color + font_weight + text_style effects as needed.\n"
            "  B) STYLIZED / RASTER-ONLY TYPOGRAPHY: 3D bubble letters, extreme perspective warping,\n"
            "     complex layered graphic calligraphy, metallic chrome lettering, or effects that cannot\n"
            "     be replicated by web fonts + SVG filters.\n"
            "     → DO NOT use a text slot. Instead:\n"
            "       1. Hide the original text slot: {\"_hidden\": true}\n"
            "       2. Spawn an extra_layer of type \"image\" at the same position.\n"
            "       3. Set rembg=true and write an image_prompt that precisely describes the stylized text\n"
            "          graphic (e.g. 'Chrome 3D bubble letters spelling SALE with metallic sheen and shadow').\n"
            "     This produces a clean raster cutout of the graphical text placed at the correct position.\n\n"

            "CRITICAL RULES:\n"
            "- LEGIBILITY IS NON-NEGOTIABLE: Every text element MUST be readable. If there is ANY doubt, add a text_style shield.\n"
            "- CONTRAST CHECK: Dark background → white/pale text. Light background → black/dark text. Never same-hue text and background without a text_style effect protecting it.\n"
            "- MONOCHROMATIC SHIELD: If you choose thematic text color that blends with the background hue, you MUST apply outline_stroke (stroke_width ≥ 4) or drop_shadow (shadow_opacity ≥ 0.85) in a contrasting color.\n"
            "- OUTLINE COLOR RULE: The outline/stroke effect_color MUST NEVER be the same color as the text fill color. The entire point of an outline is to create contrast — if outline and fill match, it's invisible and useless. Always pick a contrasting color (e.g. dark text → white/light outline, light text → dark outline).\n"
            "- BUTTON CONTRAST: bg_color and text_color on buttons must be opposite ends of the luminance scale. Dark button → white label. Light button → black label.\n"
            "- SPATIAL AWARENESS: Before assigning any text value, look at the slot's w% and h%. Narrow slots (w < 25%) need 1-4 word lines. Wide slots can fit more per line.\n"
            "- BUTTON COPY: Always 1-3 words. No exceptions. A button that overflows is broken.\n"
            "- LINE BREAKS: Add '\\n' inside long phrases to guarantee text stays inside its bounding box. When in doubt, use shorter text instead.\n"
            "- Product images: ALWAYS set rembg=true.\n"
            "- LESS IS MORE: You are ENCOURAGED to hide template slots that clutter the design. Do NOT force-fill every slot.\n"
            + (
            "- REFERENCE FIDELITY IS #1 PRIORITY: When a reference image is provided, your output MUST visually match it. "
            "Do NOT reinvent the design. Do NOT add effects, backgrounds, or overlays that aren't in the reference. "
            "If the reference is clean and minimal, your output must be clean and minimal. "
            "Copy text EXACTLY as written in the reference. Match colors EXACTLY. Match layout EXACTLY.\n"
            if _is_layerize else ""
            )
            + "- Return ONLY valid JSON."
        )

        # ── Multimodal: attach reference image (user-supplied layerize OR Silent Muse) ──
        gemini_input: list | str = orchestrator_prompt
        if reference_image_url:
            # User-provided reference raster (layerize route) — FAITHFUL REPLICATION mode
            try:
                img_path = reference_image_url.lstrip("/")
                if os.path.exists(img_path):
                    with open(img_path, "rb") as _fh:
                        _ref_bytes = _fh.read()
                    _ref_part = {"mime_type": "image/png", "data": _ref_bytes}
                    gemini_input = [
                        "I am providing a REFERENCE IMAGE. Your job is to FAITHFULLY REPLICATE this "
                        "image as closely as possible using the layered JSON template system.\n\n"
                        "CRITICAL REPLICATION RULES:\n"
                        "1. BACKGROUND: Analyze the reference image's background. If it is a solid color "
                        "(white, cream, black, etc.), use background_type='solid' with the EXACT hex color. "
                        "If it is a gradient, use background_type='gradient'. If it is a textured/photographic "
                        "background, use background_type='image' with a background_image_prompt that precisely "
                        "describes what you see (mood, color palette, lighting, texture). MATCH the reference — "
                        "do NOT invent a different background aesthetic.\n"
                        "2. TEXT: READ the actual text in the reference image and COPY IT EXACTLY into the "
                        "appropriate text slots. Preserve the exact wording, capitalization, and punctuation. "
                        "If text in the reference doesn't fit any template slot, hide the template slot and "
                        "spawn an extra_layer of type 'image' with rembg=true at the correct position.\n"
                        "3. COLORS: Match fill_color, text colors, and button colors to what you see in the "
                        "reference. Use an eyedropper mentality — pick the exact hex values visible in the image.\n"
                        "4. LAYOUT: Use structural overrides (x, y, width, height) to reposition slots so they "
                        "match the physical layout of the reference image. If an element in the reference is at "
                        "the top-left, the slot MUST be repositioned to the top-left. Do NOT use the template's "
                        "default positions if they don't match the reference.\n"
                        "5. TYPOGRAPHY: Match font weight (bold headlines should use font_weight='900'), sizing, "
                        "and style. If the reference has large bold display text, use Dela Gothic One. If clean "
                        "sans-serif, use Noto Sans JP. If elegant serif, use Shippori Mincho.\n"
                        "6. VISIBILITY: If a template slot has NO corresponding element in the reference image, "
                        "HIDE IT with {\"_hidden\": true}. Only show slots that have matching content in the reference.\n"
                        "7. EFFECTS: Only add text_style effects (outline, shadow, glow) if you can see them "
                        "in the reference image. A clean reference = clean text, no forced effects.\n"
                        "8. EXTRA LAYERS: If the reference shows elements that don't map to any template slot "
                        "(logos, decorative shapes, overlay effects), spawn them as extra_layers at the correct "
                        "position with appropriate image_prompt descriptions.\n\n"
                        "9. IMAGE PROMPTS — THIS IS CRITICAL FOR VISUAL FIDELITY:\n"
                        "   For each image slot, write an image_prompt that PRECISELY describes what you see "
                        "in that region of the reference image. Include ALL of the following:\n"
                        "   a) ART STYLE: Is it a photograph, watercolor illustration, digital art, anime, "
                        "flat vector, hand-drawn sketch, etc.? Name the exact style.\n"
                        "   b) COMPOSITION: Describe the spatial arrangement — is it a static centered subject, "
                        "a dynamic exploding/flying composition, top-down flat-lay, etc.?\n"
                        "   c) SPECIFIC ELEMENTS: List every visible object, ingredient, item in detail.\n"
                        "   d) MOOD/LIGHTING: Warm, cool, dramatic, soft, etc.\n"
                        "   e) ISOLATE THE CORE PRODUCT: You MUST STRICTLY exclude any adjacent text, signs, "
                        "labels, or decorative template clutter (like random stationery next to a ramen bowl) "
                        "from the image_prompt. Describe ONLY the core physical product. If there is text in "
                        "the reference image, it MUST go into text slots, NEVER into the image_prompt. "
                        "DO NOT mention the background, it will be removed automatically.\n"
                        "   BAD example: 'ramen bowl' (too vague — will generate a generic photo)\n"
                        "   GOOD example: 'Watercolor illustration of a dynamic ramen bowl with noodles and "
                        "ingredients flying upward out of the bowl — chashu pork slices, halved soft-boiled eggs, "
                        "nori seaweed sheets, corn kernels, chopped green onions, broth splashing — energetic "
                        "explosive composition, warm golden tones, Japanese food illustration style'\n\n"
                        "The goal is: if someone compared the reference image and your layered output side-by-side, "
                        "they should look as similar as possible. FIDELITY TO THE REFERENCE IS YOUR #1 PRIORITY.\n\n"
                        + orchestrator_prompt,
                        _ref_part,
                    ]
                    logger.info("macro_autofill: multimodal call with reference image %s", reference_image_url)
            except Exception as _ref_exc:
                logger.warning("macro_autofill: could not load reference image: %s", _ref_exc)
        elif muse_image_bytes:
            # Silent Muse raster — structural layout mockup, extract style from it
            _muse_part = {"mime_type": "image/png", "data": muse_image_bytes}
            gemini_input = [
                "I am providing a REFERENCE RASTER called 'The Silent Muse'. "
                "This image was pre-rendered specifically for this banner's canvas dimensions and slot layout, "
                "showing where each element lives on the canvas.\n"
                "CRITICAL DIRECTIVE: You are no longer inventing styles blindly. "
                "EXTRACT visual intent from this Reference Raster:\n"
                "  1. Analyze the color palette and overall mood. Apply those colors to the background and slot fills.\n"
                "  2. Look at the headline treatment. If it has strong visual pop, mandate outline_and_shadow.\n"
                "  3. Choose the closest available font family based on the aesthetic:\n"
                "       - 'Noto Sans JP' for clean modern sans-serif\n"
                "       - 'M PLUS Rounded 1c' for pop/friendly/rounded\n"
                "       - 'Shippori Mincho' for elegant serif/luxury\n"
                "       - 'Dela Gothic One' for bold impact/display\n"
                "     Output this as font_family inside the slot object.\n"
                "  4. If any text appears to flow top-to-bottom (vertical Japanese layout), "
                "output \"vertical\": true for that slot.\n"
                "  5. If any element appears deliberately angled, "
                "output \"rotation\": <degrees as float> for that slot.\n\n"
                + orchestrator_prompt,
                _muse_part,
            ]
            logger.info("macro_autofill: Silent Muse multimodal extraction call active")

        resp = await asyncio.to_thread(model.generate_content, gemini_input)
        raw = ""
        if resp.parts:
            for part in resp.parts:
                if hasattr(part, "text") and part.text:
                    raw += part.text
        raw = raw.strip()

        # Clean JSON markdown blocks
        import re
        import json as _json
        clean_raw = re.sub(r"^```(?:json)?\s*\n|\n```\s*$", "", raw, flags=re.MULTILINE).strip()

        try:
            if not clean_raw:
                raise ValueError("LLM returned empty text blocks.")
            manifest = _json.loads(clean_raw)
        except _json.JSONDecodeError as exc:
            logger.error("macro_autofill: Gemini raw output failed JSON parsing:\n%s", raw)
            raise ValueError(f"AIの応答形式が不正でした。再試行してください。(エラー: {exc})")
        logger.info("macro_autofill: Gemini manifest received: %s", list(manifest.keys()))

        # ── Phase 2: Apply design overrides + generate background image ────────
        job["progress"] = 45
        job["step"] = "デザインを適用中..."

        design = manifest.get("design", {})
        bg_override = slot_values.get("_design", {})
        if not isinstance(bg_override, dict):
            bg_override = {}

        bg_image_prompt = design.get("background_image_prompt")
        if bg_image_prompt and design.get("background_type") == "image":
            _bg_no_subject = (
                "\nCRITICAL INSTRUCTION: This image is a BACKGROUND TEXTURE ONLY. "
                "DO NOT generate realistic places, landscapes, rooms, products, people, or central subjects. "
                "The image MUST be an abstract texture, gradient, or seamless background pattern. "
                "DO NOT GENERATE ANY WORDS, LETTERS, LOGOS, OR TEXT OF ANY KIND."
            )
            safe_bg_prompt = bg_image_prompt + _bg_no_subject
            # Generate background pattern image
            try:
                bg_cjid = await image_gen_service.generate_for_slot(
                    prompt=safe_bg_prompt, pattern_id=pattern_id,
                    slot_id="__background__", width=width, height=height,
                )
                for _ in range(120):
                    bg_st = await image_gen_service.get_job_status(bg_cjid)
                    if bg_st["status"] == "completed":
                        bg_img_url = bg_st["image_url"]
                        logger.info("macro_autofill: background image generated: %s", bg_img_url)
                        # Route the generated image into the native __background__ slot
                        bg_sv = slot_values.get("__background__", {})
                        if not isinstance(bg_sv, dict):
                            bg_sv = {}
                        bg_sv["source_url"] = bg_img_url
                        slot_values["__background__"] = bg_sv
                        break
                    if bg_st["status"] == "failed":
                        logger.warning("macro_autofill: background image gen failed, falling back to solid")
                        if design.get("background_value"):
                            bg_override["background_value"] = design["background_value"]
                            bg_override["background_type"] = "solid"
                        break
                    await asyncio.sleep(0.5)
            except Exception as exc:
                logger.warning("macro_autofill: bg image gen error: %s", exc)
                if design.get("background_value"):
                    bg_override["background_value"] = design["background_value"]
        elif design.get("background_value"):
            bg_override["background_value"] = design["background_value"]
            if design.get("background_type"):
                bg_override["background_type"] = design["background_type"]

        slot_values["_design"] = bg_override

        # ── Phase 3: Apply slot fills ─────────────────────────────────────────
        job["progress"] = 55
        job["step"] = "スロットを適用中..."

        slot_fills = manifest.get("slots", {})
        image_gen_tasks: list[tuple[str, str, int, int, bool, str | None]] = []

        for slot in template.slots:
            fill_data = slot_fills.get(slot.id, {})
            if not fill_data:
                continue

            sv = slot_values.get(slot.id, {})
            if not isinstance(sv, dict):
                sv = {}

            # ── Structural override: _hidden ──────────────────────────────────
            # AI can hide a slot entirely (e.g. a text slot replaced by a raster image).
            if fill_data.get("_hidden"):
                sv["_hidden"] = True
                slot_values[slot.id] = sv
                continue  # skip all fill processing for this slot
            else:
                sv.pop("_hidden", None)  # un-hide if previously hidden

            # ── Structural override: x / y / width / height ───────────────────
            # AI can reposition/resize any slot to match the reference image layout.
            # _effective_geometry() in svg_renderer.py reads these from slot_values.
            for _geo_key in ("x", "y", "width", "height"):
                _geo_raw = fill_data.get(_geo_key)
                if _geo_raw is not None:
                    try:
                        sv[_geo_key] = max(0.0, min(100.0, float(_geo_raw)))
                    except (TypeError, ValueError):
                        pass

            # Effective slot dimensions after any AI override (used for image sizing below)
            _eff_w_pct = sv.get("width", slot.width)
            _eff_h_pct = sv.get("height", slot.height)

            # ── Text slots ────────────────────────────────────────────────────
            if slot.type.value in ("text", "image_or_text"):
                text = fill_data.get("text")
                if text:
                    sv["text"] = str(text)
                    sv["content"] = str(text)
                fill_color = fill_data.get("fill_color")
                if fill_color:
                    sv["color"] = fill_color
                font_size = fill_data.get("font_size")
                if font_size:
                    sv["font_size"] = str(font_size)
                font_weight = fill_data.get("font_weight")
                if font_weight:
                    sv["font_weight"] = str(font_weight)
                text_style = fill_data.get("text_style")
                if text_style and isinstance(text_style, dict) and text_style.get("effect_type"):
                    sv["text_style"] = text_style
                # ── Silent Muse extracted typography fields ───────────────────
                font_family = fill_data.get("font_family")
                if font_family:
                    sv["font_family"] = str(font_family)
                vertical = fill_data.get("vertical")
                if vertical is not None:
                    sv["vertical"] = bool(vertical)
                rotation = fill_data.get("rotation")
                if rotation is not None:
                    try:
                        sv["rotation"] = max(-180.0, min(180.0, float(rotation)))
                    except (TypeError, ValueError):
                        pass

            # ── Button slots ──────────────────────────────────────────────────
            elif slot.type.value == "button":
                text = fill_data.get("text")
                if text:
                    sv["text"] = str(text)
                    sv["content"] = str(text)
                    sv["label"] = str(text)
                bg_color = fill_data.get("bg_color")
                if bg_color:
                    sv["bg_color"] = bg_color
                text_color = fill_data.get("text_color")
                if text_color:
                    sv["text_color"] = text_color
                    
                bg_image_prompt = fill_data.get("bg_image_prompt")
                if bg_image_prompt:
                    # Request a perfect 1:1 square material/texture tile.
                    # Generating extreme math aspect ratios (e.g. 400x45) forces Imagen to
                    # pad the canvas (letterboxing) since it only natively outputs 16:9 or 1:1.
                    # SVG xMidYMid slice will seamlessly map this square tile into the button bounds.
                    sw, sh = 256, 256
                    
                    # Prevent hallucinated text + enforce flat orthographic fill for button backgrounds
                    _no_text_constraint = (
                        "\nCRITICAL: DO NOT GENERATE ANY WORDS, LETTERS, INITIALS, "
                        "TYPOGRAPHY, OR TEXT OF ANY KIND IN THIS IMAGE. "
                        "It must be a blank graphic/texture with absolutely NO text. "
                        "It MUST be perfectly flat, orthographic, and directly facing the camera. "
                        "The shape MUST perfectly fill the entire image frame from edge-to-edge. "
                        "DO NOT generate floating 3D objects, perspective angles, or drop shadows "
                        "that leave empty margins around the element."
                    )
                    safe_prompt = bg_image_prompt + _no_text_constraint
                    # For button rasterization, temporarily disable rembg to test pure generated blocks without cropping errors
                    image_gen_tasks.append((slot.id, safe_prompt, sw, sh, False, None))

            # ── Image slots ───────────────────────────────────────────────────
            # !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
            # !! DO NOT MODIFY THIS BLOCK — AI ASSISTANTS (Gemini, Copilot,   !!
            # !! Claude, etc.) MUST NOT change the constraint strings, rembg  !!
            # !! defaults, or green-screen logic below. These constraints     !!
            # !! prevent text hallucination and ensure clean background        !!
            # !! removal. Any "optimisation" that weakens them WILL break     !!
            # !! product image generation. If you need to change image gen    !!
            # !! behaviour, modify the Gemini orchestrator prompt instead.    !!
            # !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
            elif slot.type.value == "image":
                img_prompt = fill_data.get("image_prompt")
                if img_prompt:
                    sw = int(_eff_w_pct / 100 * width)
                    sh = int(_eff_h_pct / 100 * height)
                    # Scale proportionally to meet model minimum (256px)
                    _min_dim = 256
                    if sw < _min_dim or sh < _min_dim:
                        _scale = _min_dim / min(sw, sh) if min(sw, sh) > 0 else 1.0
                        sw = max(int(sw * _scale), _min_dim)
                        sh = max(int(sh * _scale), _min_dim)

                    # LOCKED: Always use rembg + green screen for product images.
                    # Gemini's manifest rembg flag is IGNORED — this is intentional.
                    use_rembg = True
                    gen_bg = fill_data.get("gen_bg_color")

                    # LOCKED: Unified constraint for BOTH layerize and creative modes.
                    # Forces plain green-screen bg + no-text rule on every product image.
                    _product_constraint = (
                        "\nCRITICAL RULES FOR THIS PRODUCT IMAGE:"
                        "\n1. DO NOT UNDER ANY CIRCUMSTANCE GENERATE ANY WORDS, LETTERS, WATERMARKS, LOGOS, "
                        "TEXT, LABELS, BRAND NAMES, SIGNS, OR TYPOGRAPHY OF ANY KIND IN THIS IMAGE."
                        "\n2. The background MUST be a SOLID, UNIFORM, BRIGHT GREEN (#00FF00) "
                        "chroma-key background. No gradients, no scenery, no textures — "
                        "ONLY a flat uniform bright green behind the subject."
                        "\n3. The product must be centered with generous margins on all sides."
                        "\n4. The product must NOT touch or be cropped by any edge of the frame."
                        "\n5. ONLY generate the pure, physical product/subject. "
                        "Ignore any adjacent banners or floating graphical elements."
                        "\n6. DO NOT UNDER ANY CIRCUMSTANCE generate translucent, transparent, or volumetric effects. "
                        "NO glass, NO smoke, NO steam, NO glowing light beams, NO reflections, and NO fire. "
                        "The product must be 100% solid and entirely opaque so the background can be structurally removed."
                    )
                    img_prompt = img_prompt + _product_constraint + _ANTI_CROP_CONSTRAINT
                    image_gen_tasks.append((slot.id, img_prompt, sw, sh, use_rembg, gen_bg))

            # ── Shape / decorative fill ───────────────────────────────────────
            shape_fill = fill_data.get("fill_color")
            if shape_fill and slot.type.value not in ("text", "button", "image_or_text"):
                sv["fill"] = shape_fill

            # ── Universal opacity ─────────────────────────────────────────────
            opacity = fill_data.get("opacity")
            if opacity is not None:
                try:
                    sv["opacity"] = max(0.0, min(1.0, _safe_float(opacity, 1.0)))
                except (ValueError, TypeError):
                    pass

            slot_values[slot.id] = sv

        # ── Phase 3b: Inject extra layers from AI ─────────────────────────────
        extra_layers = manifest.get("extra_layers", [])
        custom_layers = slot_values.get("_custom_layers", [])
        if not isinstance(custom_layers, list):
            custom_layers = []

        # Purge stale ai_extra_* layers from previous runs so we don't get
        # duplicates (old ai_extra_0 + new ai_extra_0) which causes the
        # source_url update to hit the old entry and leave the new one empty.
        custom_layers = [l for l in custom_layers if not str(l.get("id", "")).startswith("ai_extra_")]

        if extra_layers and isinstance(extra_layers, list):
            extra_image_tasks: list[tuple[str, str, int, int]] = []

            for idx, el in enumerate(extra_layers):
                cid = f"ai_extra_{idx}"
                layer_type = el.get("type", "rect")

                blend_mode = el.get("blend_mode", "normal") or "normal"
                use_rembg_extra = bool(el.get("rembg", False))
                if layer_type == "image" and el.get("image_prompt"):
                    # Queue image generation for decorative layers
                    ew = max(int(_safe_float(el.get("width", 20)) / 100 * width), 64)
                    eh = max(int(_safe_float(el.get("height", 20)) / 100 * height), 64)
                    extra_prompt = el["image_prompt"]
                    if use_rembg_extra:
                        extra_prompt = extra_prompt + _ANTI_CROP_CONSTRAINT
                    extra_image_tasks.append((cid, extra_prompt, ew, eh, use_rembg_extra))
                    custom_layers.append({
                        "id": cid, "type": "image",
                        "x": _safe_float(el.get("x", 0)),
                        "y": _safe_float(el.get("y", 0)),
                        "width": _safe_float(el.get("width", 20), 20),
                        "height": _safe_float(el.get("height", 20), 20),
                        "opacity": _safe_float(el.get("opacity", 1.0), 1.0),
                        "blend_mode": blend_mode,
                        "source_url": "",  # will be filled after generation
                        "label": el.get("label", f"AI Layer {idx}"),
                    })
                else:
                    custom_layers.append({
                        "id": cid, "type": layer_type,
                        "x": _safe_float(el.get("x", 0)),
                        "y": _safe_float(el.get("y", 0)),
                        "width": _safe_float(el.get("width", 20), 20),
                        "height": _safe_float(el.get("height", 20), 20),
                        "fill": el.get("fill", "#FFFFFF"),
                        "opacity": _safe_float(el.get("opacity", 1.0), 1.0),
                        "blend_mode": blend_mode,
                        "label": el.get("label", f"AI Layer {idx}"),
                    })

            slot_values["_custom_layers"] = custom_layers

            # Generate images for decorative extra layers
            if extra_image_tasks:
                async def gen_extra_img(cid: str, prompt: str, iw: int, ih: int, use_rembg_flag: bool) -> tuple[str, str | None]:
                    try:
                        cjid = await image_gen_service.generate_for_slot(
                            prompt=prompt, pattern_id=pattern_id,
                            slot_id=cid, width=iw, height=ih,
                        )
                        for _ in range(120):
                            st = await image_gen_service.get_job_status(cjid)
                            if st["status"] == "completed":
                                img_url = st["image_url"]
                                if use_rembg_flag and img_url:
                                    try:
                                        img_path = img_url.lstrip("/")
                                        if os.path.exists(img_path):
                                            with open(img_path, "rb") as fh:
                                                raw = fh.read()
                                            transparent = await asyncio.to_thread(_remove_background_alpha, raw)
                                            rb_fname = f"{job_id}_rembg_{cid}.png"
                                            with open(os.path.join(OUTPUT_DIR, rb_fname), "wb") as fh:
                                                fh.write(transparent)
                                            img_url = f"/static/generated/{rb_fname}"
                                    except Exception as rexc:
                                        logger.warning("rembg for extra layer %s failed: %s", cid, rexc)
                                return cid, img_url
                            if st["status"] == "failed":
                                return cid, None
                            await asyncio.sleep(0.5)
                        return cid, None
                    except Exception:
                        return cid, None

                extra_results = await asyncio.gather(
                    *[gen_extra_img(cid, p, iw, ih, rb) for cid, p, iw, ih, rb in extra_image_tasks],
                    return_exceptions=True,
                )
                for res in extra_results:
                    if isinstance(res, Exception):
                        continue
                    eid, url = res
                    if url:
                        for lyr in custom_layers:
                            if lyr["id"] == eid:
                                lyr["source_url"] = url
                                break
                                
        # ── Phase 3c: Apply absolute Z-Order stack (layer_order) ──────────────
        ai_order = manifest.get("layer_order", [])
        if isinstance(ai_order, list) and ai_order:
            # We want to use the exact order specified by the AI.
            # But we must ensure all template slots and custom layers exist.
            final_order = []
            seen = set()
            for lid in ai_order:
                if isinstance(lid, str):
                    final_order.append(lid)
                    seen.add(lid)
            
            # Append any missing template slots
            for slot in template.slots:
                if slot.id not in seen:
                    final_order.append(slot.id)
            
            # Append any missing custom layers
            for lyr in custom_layers:
                lid = lyr.get("id")
                if lid and lid not in seen:
                    final_order.append(lid)
                    
            if "__background__" in final_order:
                final_order.remove("__background__")
            final_order.append("__background__")
            
            slot_values["_order"] = final_order
        else:
            # Fallback legacy append method
            legacy_order = [s.id for s in template.slots]
            for lyr in custom_layers:
                lid = lyr.get("id")
                if lid:
                    legacy_order.append(lid)
                    
            if "__background__" in legacy_order:
                legacy_order.remove("__background__")
            legacy_order.append("__background__")
            
            slot_values["_order"] = legacy_order

        # ── Phase 4: Generate images for image slots (with rembg) ─────────────
        if image_gen_tasks:
            job["progress"] = 70
            job["step"] = f"{len(image_gen_tasks)}枚の画像を生成中..."

            async def gen_image(
                slot_id: str, prompt: str, iw: int, ih: int,
                use_rembg: bool, gen_bg: str | None,
            ) -> tuple[str, dict | None]:
                try:
                    cjid = await image_gen_service.generate_for_slot(
                        prompt=prompt, pattern_id=pattern_id,
                        slot_id=slot_id, width=iw, height=ih,
                    )
                    for _ in range(120):
                        st = await image_gen_service.get_job_status(cjid)
                        if st["status"] == "completed":
                            result = {"slot_type": "image", "source_url": st["image_url"], "fit": "cover"}

                            # Apply rembg if flagged for product images
                            if use_rembg and st.get("image_url"):
                                logger.info("rembg: starting background removal for slot %s (use_rembg=%s)", slot_id, use_rembg)
                                try:
                                    img_path = st["image_url"].lstrip("/")
                                    if os.path.exists(img_path):
                                        with open(img_path, "rb") as f:
                                            raw_bytes = f.read()
                                        logger.info("rembg: read %d bytes from %s", len(raw_bytes), img_path)
                                        transparent = await asyncio.to_thread(
                                            _remove_background_alpha, raw_bytes
                                        )
                                        logger.info("rembg: got %d bytes output for slot %s", len(transparent) if transparent else 0, slot_id)
                                        if transparent and len(transparent) > 500:
                                            rembg_fname = f"{job_id}_rembg_{slot_id}.png"
                                            rembg_path = os.path.join(OUTPUT_DIR, rembg_fname)
                                            with open(rembg_path, "wb") as f:
                                                f.write(transparent)
                                            result["source_url"] = f"/static/generated/{rembg_fname}"
                                            logger.info("rembg applied for slot %s → %s", slot_id, rembg_fname)
                                        else:
                                            logger.warning("rembg: output too small for slot %s, using original image", slot_id)
                                    else:
                                        logger.warning("rembg: file not found at %s", img_path)
                                except Exception as rembg_exc:
                                    logger.warning("rembg failed for slot %s: %s", slot_id, rembg_exc)

                            return slot_id, result
                        if st["status"] == "failed":
                            return slot_id, None
                        await asyncio.sleep(0.5)
                    return slot_id, None
                except Exception as exc:
                    logger.warning("Image gen failed for slot %s: %s", slot_id, exc)
                    return slot_id, None

            results = await asyncio.gather(
                *[gen_image(sid, p, iw, ih, rembg, gbg)
                  for sid, p, iw, ih, rembg, gbg in image_gen_tasks],
                return_exceptions=True,
            )
            for res in results:
                if isinstance(res, Exception):
                    logger.warning("Image gen exception: %s", res)
                    continue
                sid, val = res
                if val:
                    existing = slot_values.get(sid, {})
                    if not isinstance(existing, dict):
                        existing = {}
                    
                    # If this is a button slot, map the generated image to bg_image_url
                    is_btn = any(s.id == sid and s.type.value == "button" for s in template.slots)
                    if is_btn and "source_url" in val:
                        val["bg_image_url"] = val["source_url"]
                        del val["source_url"]
                        
                    existing.update(val)
                    slot_values[sid] = existing

        # ── Phase 5: Render final composite PNG for preview ──────────────────
        job["progress"] = 90
        job["step"] = "プレビューを生成中..."

        from app.routers.generate import _embed_local_images, _embed_google_fonts, _svg_to_png

        effective_template = template
        design_overrides = slot_values.get("_design")
        if isinstance(design_overrides, dict) and design_overrides.get("background_value"):
            effective_template = template.model_copy(deep=True)
            effective_template.design.background_value = design_overrides["background_value"]
            if design_overrides.get("background_type"):
                effective_template.design.background_type = design_overrides["background_type"]

        svg_string = svg_renderer.render(effective_template, slot_values)
        svg_embedded = await asyncio.to_thread(_embed_local_images, svg_string)
        svg_embedded = _embed_google_fonts(svg_embedded)
        png_bytes = await asyncio.to_thread(_svg_to_png, svg_embedded, width, height)

        composite_filename = f"{job_id}_composite.png"
        with open(os.path.join(OUTPUT_DIR, composite_filename), "wb") as fh:
            fh.write(png_bytes)

        job["file_url"] = f"/static/generated/{composite_filename}"

        # ── Phase 6: Automatic Art Director Critique (Auto-Fix) ──────────────────
        job["progress"] = 95
        job["step"] = "AIアートディレクターによる最終微調整..."
        try:
            slot_values = await _adjust_canvas_with_vision(
                nano_client=nano_client,
                template=effective_template,
                slot_values=slot_values,
                png_bytes=png_bytes,
                reference_image_url=reference_image_url,
            )
            # Phase 6 doesn't generate new layers or backgrounds — discard pending
            slot_values.pop("_pending_new_layers", None)
            slot_values.pop("_pending_bg_override", None)
            # Re-render composite with the adjusted layout
            svg_string = svg_renderer.render(effective_template, slot_values)
            svg_embedded = await asyncio.to_thread(_embed_local_images, svg_string)
            svg_embedded = _embed_google_fonts(svg_embedded)
            png_bytes = await asyncio.to_thread(_svg_to_png, svg_embedded, width, height)
            
            with open(os.path.join(OUTPUT_DIR, composite_filename), "wb") as fh:
                fh.write(png_bytes)
        except Exception as critique_exc:
            logger.warning("Phase 6 Auto-Fix failed, skipping: %s", critique_exc)

        # Stage for session write in polling handler
        job["final_slots"] = slot_values
        job["pattern_id"] = pattern_id

        job["progress"] = 100
        job["step"] = "完了"
        job["status"] = "completed"

    except Exception as exc:
        logger.error("Macro auto-fill pipeline failed for job %s: %s", job_id, exc)
        job["status"] = "failed"
        job["error"] = str(exc)
        job["progress"] = 0


@router.get("/progress/{job_id}", response_class=HTMLResponse)
async def blend_progress(request: Request, job_id: str):
    """Poll the native pipeline status.

    While processing: returns the progress spinner partial.
    On completion: persists session, then returns canvas OOB refresh + success message.
    """
    if job_id not in _jobs:
        return templates.TemplateResponse(
            request,
            "partials/generate_result.html",
            {"status": "error", "error": f"Job not found: {job_id}"},
        )

    job = _jobs[job_id]
    poll_url = f"/api/ai-generation/progress/{job_id}"

    if job["status"] == "processing":
        return templates.TemplateResponse(
            request,
            "partials/generate_result.html",
            {
                "status": "processing",
                "job_id": job_id,
                "progress": job["progress"],
                "mode": "ai",
                "poll_url": poll_url,
                "is_polling": True,
            },
        )

    if job["status"] == "failed":
        return templates.TemplateResponse(
            request,
            "partials/generate_result.html",
            {"status": "error", "error": job.get("error", "生成中にエラーが発生しました。")},
        )

    # Completed — persist session, refresh canvas + slot editor via OOB
    from app.routers.layers import _render_canvas

    pattern_id = job.get("pattern_id", "")
    if pattern_id and "final_slots" in job:
        request.session[f"slots_{pattern_id}"] = job["final_slots"]

    canvas_response = _render_canvas(request, pattern_id)
    body = canvas_response.body.decode()

    # Inject OOB on the canvas div so HTMX swaps it alongside #generate-result
    body = body.replace('id="preview-canvas"', 'id="preview-canvas" hx-swap-oob="true"', 1)

    # Render comparison-tabs HTML via the generate_result template (AI版 tab)
    file_url = job.get("file_url", "")
    result_html = templates.env.get_template("partials/generate_result.html").render(
        status="completed",
        mode="ai",
        file_url=file_url,
        ai_file_url=file_url,  # same composite for both tabs in this pipeline
        pattern_id=pattern_id,
    )

    # _render_canvas already includes OOB for sidebar, slot-editor-panel,
    # and ai-tab-slots — no need to add a duplicate slot-editor OOB here.
    return HTMLResponse(content=result_html + body)


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

async def _adjust_canvas_with_vision(
    nano_client, template, slot_values: dict, png_bytes: bytes,
    reference_image_url: str | None, user_comment: str | None = None,
) -> dict:
    """Core function to run Gemini Vision on the canvas to fix layout issues.

    Returns the mutated *slot_values* dict.  The caller is responsible for
    generating images for any ``new_layers`` entries that Gemini returns
    (stored under ``slot_values["_pending_new_layers"]``).
    """
    import json, os, re, asyncio

    current_art = {"mime_type": "image/png", "data": png_bytes}
    gemini_input = []

    if reference_image_url:
        img_path = reference_image_url.lstrip("/")
        if os.path.exists(img_path):
            with open(img_path, "rb") as fh:
                _ref_bytes = fh.read()
            _mime = "image/jpeg" if img_path.lower().endswith((".jpg", ".jpeg")) else "image/png"
            gemini_input = [
                "I am providing a REFERENCE IMAGE. This is the original design intent and aesthetic layout you MUST match.",
                {"mime_type": _mime, "data": _ref_bytes},
                "And here is the CURRENT OUTPUT IMAGE generated by the system. It may have errors.",
                current_art,
            ]

    if not gemini_input:
        gemini_input = [
            "I am providing the CURRENT OUTPUT IMAGE of a generated banner design. It may have layout errors.",
            current_art,
        ]

    # Inject user's correction instruction (highest priority)
    if user_comment:
        gemini_input.append(
            f"\n── USER INSTRUCTION (HIGHEST PRIORITY) ──\n"
            f"The designer has the following request:\n\"{user_comment}\"\n"
            f"You MUST address this instruction first. It takes priority over your own analysis.\n"
        )

    # Filter out internal keys that Gemini shouldn't see
    _visible = {k: v for k, v in slot_values.items() if not k.startswith("_")}
    state_json = json.dumps(_visible, indent=2, ensure_ascii=False)
    gemini_input.extend([
        f"\nHere is the current JSON parameter state containing x, y, width, height, opacity, and text_style for each layer:\n```json\n{state_json}\n```\n",
        "── AI ART DIRECTOR PROTOCOL ──\n"
        "You are an expert Art Director reviewing the CURRENT OUTPUT IMAGE.\n"
        "Your job is to identify layout errors and output JSON to mathematically fix them.\n\n"
        "CHECK FOR:\n"
        "1. OVERLAPPING/CLIPPED ELEMENTS: Is text bleeding out of bounds? Is the product unnaturally cut off at the edges? Are elements crowding each other?\n"
        "2. LEGIBILITY & CONTRAST: Is text unreadable against the background? If so, inject a text_style shield (e.g. outline_stroke, drop_shadow).\n"
        "3. REFERENCE FIDELITY: If a REFERENCE IMAGE was provided, ensure the layout, positioning, scaling, and text exactly match it.\n"
        "4. Z-ORDER: Check layer_order. Is smoke behind the product? Are text layers behind ambient effects?\n"
        "5. USER INSTRUCTION: If the designer provided a specific instruction, execute it precisely.\n"
        "6. BACKGROUND QUALITY: Is the background ugly, mismatched, or clashing with the design? If so, use background_override to regenerate it.\n"
        "7. OUTLINE COLOR: If any text has outline_stroke or outline_and_shadow, the effect_color MUST NEVER match the text fill color — outlines exist for contrast. Fix any violations.\n\n"
        "OUTPUT:\n"
        "Return ONLY valid JSON in this exact format:\n"
        '{\n'
        '  "feedback": "日本語で1〜2文の分析コメント（何が問題で、何を修正したかを説明）",\n'
        '  "layer_adjustments": {\n'
        '    "slot_id_1": { "x": 10, "y": 20, "text_style": {"effect_type": "drop_shadow", "shadow_opacity": 0.5} },\n'
        '    "slot_id_2": { "width": 80, "height": 20, "opacity": 0.8 },\n'
        '    "layer_order": ["__background__", "ai_extra_0", "slot_id_2", "slot_id_1"]\n'
        '  },\n'
        '  "new_layers": [\n'
        '    {\n'
        '      "type": "image",\n'
        '      "x": 30, "y": 60, "width": 40, "height": 30,\n'
        '      "image_prompt": "rising hot white steam on pure black background",\n'
        '      "blend_mode": "screen", "opacity": 0.8, "rembg": false,\n'
        '      "label": "Steam FX"\n'
        '    }\n'
        '  ],\n'
        '  "background_override": {\n'
        '    "background_type": "image",\n'
        '    "background_image_prompt": "dark moody ramen shop interior, warm lighting, blurred"\n'
        '  }\n'
        '}\n\n'
        "RULES:\n"
        "- ONLY output adjustments for layers that NEED fixing. If a layer is fine, do NOT include it.\n"
        "- NEVER invent new layer IDs inside layer_adjustments. You can only adjust layers that exist in the provided JSON state.\n"
        "- To ADD new layers (FX, decorative shapes, accent images), put them in new_layers. Each new layer needs: type, x, y, width, height, and either image_prompt (for generated images) or fill (for colored shapes).\n"
        "- For new image layers with blend_mode 'screen': image_prompt MUST specify 'on pure BLACK background'. For 'multiply': 'on pure WHITE background'.\n"
        "- new_layers is OPTIONAL. Only add layers if the design genuinely needs them or the user asked for them. Omit it or pass [] if no new layers are needed.\n"
        "- background_override is OPTIONAL. Only include it to regenerate the background. Options:\n"
        "  * {\"background_type\": \"image\", \"background_image_prompt\": \"description of desired background\"} — generates a new background image.\n"
        "  * {\"background_type\": \"solid\", \"background_value\": \"#hex\"} — replaces with a solid color.\n"
        "  * {\"background_type\": \"gradient\", \"background_value\": \"#hex1,#hex2\"} — replaces with a gradient.\n"
        "  The background_image_prompt must describe an ABSTRACT TEXTURE or SCENE — never mention the product.\n"
        "- OUTLINE COLOR: effect_color for outline_stroke / outline_and_shadow MUST NEVER be the same as the text fill color. Always pick a contrasting color.\n"
        "- ALIGNMENT: Ensure bounding boxes and elements hit visually pleasant alignments (centered or grid-aligned).\n"
        "- ALL coordinates (x, y, w, h) are percentages (0-100) relative to the canvas.\n",
    ])

    # Use the Gemini SDK directly (nano_client wraps google.generativeai)
    model = nano_client._get_model()
    resp = await asyncio.to_thread(model.generate_content, gemini_input)
    raw_response = ""
    if resp.parts:
        for part in resp.parts:
            if hasattr(part, "text") and part.text:
                raw_response += part.text
    raw_response = raw_response.strip()

    match = re.search(r"```(?:json)?\s*(.*?)\s*```", raw_response, re.DOTALL)
    if match:
        raw_response = match.group(1).strip()

    manifest = json.loads(raw_response)

    # ── Apply layer adjustments to existing layers ──
    adjustments = manifest.get("layer_adjustments", {})
    for lid, adj in adjustments.items():
        if lid == "layer_order":
            slot_values["_order"] = adj
            continue
        if not isinstance(adj, dict):
            continue
        if lid not in slot_values or not isinstance(slot_values[lid], dict):
            slot_values[lid] = {}
        for k, v in adj.items():
            # Deep-merge nested dicts (e.g. text_style) instead of replacing
            if isinstance(v, dict) and isinstance(slot_values[lid].get(k), dict):
                slot_values[lid][k].update(v)
            else:
                slot_values[lid][k] = v

    # ── Stash new layers for the caller to generate images for ──
    new_layers = manifest.get("new_layers", [])
    if isinstance(new_layers, list) and new_layers:
        slot_values["_pending_new_layers"] = new_layers

    # ── Stash background override for the caller to process ──
    bg_override = manifest.get("background_override")
    if isinstance(bg_override, dict) and bg_override.get("background_type"):
        slot_values["_pending_bg_override"] = bg_override

    slot_values["_last_auto_fix_feedback"] = manifest.get("feedback", "レイアウトを微調整しました。")
    return slot_values


# ── AI ART DIRECTOR (Auto-Fix Canvas Loop) ──────────────────────────────────
@router.post("/auto-fix/{pattern_id}")
async def run_auto_fix(request: Request, pattern_id: str):
    """Manual Art Director button — renders canvas, sends screenshot to Gemini
    Vision, applies coordinate/style adjustments, optionally generates new
    layers, then returns OOB-swapped HTML for the canvas, sidebar, and feedback
    panel.  Accepts an optional ``user_comment`` form field so the designer can
    give the AI specific instructions."""
    try:
        import asyncio

        template_service = request.app.state.template_service
        svg_renderer = request.app.state.svg_renderer
        image_gen_service = request.app.state.image_generation_service
        template = template_service.get_template(pattern_id)
        if not template:
            return HTMLResponse(
                content='<span id="auto-fix-btn-content" hx-swap-oob="true"'
                ' class="text-red-500 text-xs">テンプレートが見つかりません</span>'
            )

        form = await request.form()
        user_comment = str(form.get("user_comment", "") or "").strip() or None

        slot_values = dict(request.session.get(f"slots_{pattern_id}", {}))

        reference_image_url = None
        for key, value in request.session.items():
            if key.startswith("layerize_source_") and isinstance(value, dict):
                reference_image_url = value.get("url")
                break

        # ── Step 1: Render the live canvas locally ──
        from app.routers.generate import _embed_local_images, _embed_google_fonts, _svg_to_png
        svg_string = svg_renderer.render(template, slot_values)
        svg_embedded = await asyncio.to_thread(_embed_local_images, svg_string)
        svg_embedded = _embed_google_fonts(svg_embedded)
        w, h = template.meta.width, template.meta.height
        png_bytes = await asyncio.to_thread(_svg_to_png, svg_embedded, w, h)

        # ── Step 2: Run Vision Evaluate ──
        nano_client = request.app.state.nano_banana_client
        slot_values = await _adjust_canvas_with_vision(
            nano_client=nano_client,
            template=template,
            slot_values=slot_values,
            png_bytes=png_bytes,
            reference_image_url=reference_image_url,
            user_comment=user_comment,
        )

        # ── Step 2b: Generate images for any new layers the AI requested ──
        pending = slot_values.pop("_pending_new_layers", [])
        if pending and isinstance(pending, list):
            custom_layers = slot_values.get("_custom_layers", [])
            if not isinstance(custom_layers, list):
                custom_layers = []

            # Determine next ai_fix_* index (avoid collision with existing)
            existing_fix_ids = {
                l.get("id") for l in custom_layers
                if str(l.get("id", "")).startswith("ai_fix_")
            }
            next_idx = 0
            while f"ai_fix_{next_idx}" in existing_fix_ids:
                next_idx += 1

            extra_image_tasks: list[tuple[str, str, int, int, bool]] = []

            for el in pending:
                if not isinstance(el, dict):
                    continue
                cid = f"ai_fix_{next_idx}"
                next_idx += 1
                layer_type = el.get("type", "rect")
                blend_mode = el.get("blend_mode", "normal") or "normal"
                use_rembg_extra = bool(el.get("rembg", False))

                if layer_type == "image" and el.get("image_prompt"):
                    ew = max(int(_safe_float(el.get("width", 20)) / 100 * w), 64)
                    eh = max(int(_safe_float(el.get("height", 20)) / 100 * h), 64)
                    extra_prompt = el["image_prompt"]
                    if use_rembg_extra:
                        extra_prompt = extra_prompt + _ANTI_CROP_CONSTRAINT
                    extra_image_tasks.append((cid, extra_prompt, ew, eh, use_rembg_extra))
                    custom_layers.append({
                        "id": cid, "type": "image",
                        "x": _safe_float(el.get("x", 0)),
                        "y": _safe_float(el.get("y", 0)),
                        "width": _safe_float(el.get("width", 20), 20),
                        "height": _safe_float(el.get("height", 20), 20),
                        "opacity": _safe_float(el.get("opacity", 1.0), 1.0),
                        "blend_mode": blend_mode,
                        "source_url": "",
                        "label": el.get("label", f"AI Fix Layer {cid}"),
                    })
                else:
                    custom_layers.append({
                        "id": cid, "type": layer_type,
                        "x": _safe_float(el.get("x", 0)),
                        "y": _safe_float(el.get("y", 0)),
                        "width": _safe_float(el.get("width", 20), 20),
                        "height": _safe_float(el.get("height", 20), 20),
                        "fill": el.get("fill", "#FFFFFF"),
                        "opacity": _safe_float(el.get("opacity", 1.0), 1.0),
                        "blend_mode": blend_mode,
                        "label": el.get("label", f"AI Fix Layer {cid}"),
                    })

            slot_values["_custom_layers"] = custom_layers

            # Generate images for new layers in parallel
            if extra_image_tasks:
                async def _gen_fix_img(cid: str, prompt: str, iw: int, ih: int, use_rb: bool) -> tuple[str, str | None]:
                    try:
                        cjid = await image_gen_service.generate_for_slot(
                            prompt=prompt, pattern_id=pattern_id,
                            slot_id=cid, width=iw, height=ih,
                        )
                        for _ in range(120):
                            st = await image_gen_service.get_job_status(cjid)
                            if st["status"] == "completed":
                                img_url = st["image_url"]
                                if use_rb and img_url:
                                    try:
                                        img_path = img_url.lstrip("/")
                                        if os.path.exists(img_path):
                                            with open(img_path, "rb") as fh:
                                                raw = fh.read()
                                            transparent = await asyncio.to_thread(_remove_background_alpha, raw)
                                            rb_fname = f"autofix_rembg_{cid}.png"
                                            with open(os.path.join(OUTPUT_DIR, rb_fname), "wb") as fh:
                                                fh.write(transparent)
                                            img_url = f"/static/generated/{rb_fname}"
                                    except Exception as rexc:
                                        logger.warning("rembg for fix layer %s failed: %s", cid, rexc)
                                return cid, img_url
                            if st["status"] == "failed":
                                return cid, None
                            await asyncio.sleep(0.5)
                        return cid, None
                    except Exception:
                        return cid, None

                results = await asyncio.gather(
                    *[_gen_fix_img(cid, p, iw, ih, rb) for cid, p, iw, ih, rb in extra_image_tasks],
                    return_exceptions=True,
                )
                for res in results:
                    if isinstance(res, Exception):
                        continue
                    eid, url = res
                    if url:
                        for lyr in custom_layers:
                            if lyr["id"] == eid:
                                lyr["source_url"] = url
                                break

            # Insert new layer IDs into the layer order
            order = slot_values.get("_order", [])
            if isinstance(order, list):
                new_ids = {l["id"] for l in custom_layers if l["id"].startswith("ai_fix_")}
                existing_in_order = set(order)
                for nid in sorted(new_ids - existing_in_order):
                    # Insert just before __background__ (or at the end)
                    bg_idx = None
                    for i, lid in enumerate(order):
                        if lid == "__background__":
                            bg_idx = i
                            break
                    if bg_idx is not None:
                        order.insert(bg_idx, nid)
                    else:
                        order.append(nid)
                slot_values["_order"] = order

        # ── Step 2c: Handle background override if the AI requested one ──
        pending_bg = slot_values.pop("_pending_bg_override", None)
        if isinstance(pending_bg, dict) and pending_bg.get("background_type"):
            bg_design = slot_values.get("_design", {})
            if not isinstance(bg_design, dict):
                bg_design = {}

            bg_type = pending_bg["background_type"]
            if bg_type == "image" and pending_bg.get("background_image_prompt"):
                _bg_no_subject = (
                    "\nCRITICAL INSTRUCTION: This image is a BACKGROUND TEXTURE ONLY. "
                    "DO NOT generate realistic places, landscapes, rooms, products, people, or central subjects. "
                    "The image MUST be an abstract texture, gradient, or seamless background pattern. "
                    "DO NOT GENERATE ANY WORDS, LETTERS, LOGOS, OR TEXT OF ANY KIND."
                )
                safe_bg_prompt = pending_bg["background_image_prompt"] + _bg_no_subject
                try:
                    bg_cjid = await image_gen_service.generate_for_slot(
                        prompt=safe_bg_prompt, pattern_id=pattern_id,
                        slot_id="__background__", width=w, height=h,
                    )
                    for _ in range(120):
                        bg_st = await image_gen_service.get_job_status(bg_cjid)
                        if bg_st["status"] == "completed":
                            bg_img_url = bg_st["image_url"]
                            bg_sv = slot_values.get("__background__", {})
                            if not isinstance(bg_sv, dict):
                                bg_sv = {}
                            bg_sv["source_url"] = bg_img_url
                            slot_values["__background__"] = bg_sv
                            bg_design["background_type"] = "image"
                            logger.info("auto-fix: background image regenerated: %s", bg_img_url)
                            break
                        if bg_st["status"] == "failed":
                            logger.warning("auto-fix: background image gen failed")
                            break
                        await asyncio.sleep(0.5)
                except Exception as bg_exc:
                    logger.warning("auto-fix: bg image gen error: %s", bg_exc)
            elif bg_type == "solid" and pending_bg.get("background_value"):
                bg_design["background_value"] = pending_bg["background_value"]
                bg_design["background_type"] = "solid"
            elif bg_type == "gradient" and pending_bg.get("background_value"):
                bg_design["background_value"] = pending_bg["background_value"]
                bg_design["background_type"] = "gradient"

            slot_values["_design"] = bg_design

        request.session[f"slots_{pattern_id}"] = slot_values

        # ── Step 3: Render Canvas + UI Swap via OOB ──
        # _render_canvas already returns canvas HTML + OOB sidebar + OOB
        # slot-editor + OOB ai-tab. We inject hx-swap-oob on the canvas div
        # so it swaps via OOB (the button uses hx-swap="none").
        from app.routers.layers import _render_canvas
        canvas_response = _render_canvas(request, pattern_id)
        body = canvas_response.body.decode()
        body = body.replace('id="preview-canvas"', 'id="preview-canvas" hx-swap-oob="true"')

        # OOB: feedback banner
        feedback_str = slot_values.get("_last_auto_fix_feedback", "レイアウトを微調整しました。")
        feedback_oob = (
            '<div id="auto-fix-feedback" hx-swap-oob="innerHTML"'
            ' class="p-4 mb-4 bg-purple-50 border border-purple-200 rounded-lg'
            ' text-sm text-purple-900 shadow-sm">'
            f'<strong class="font-bold">AIアートディレクター:</strong> {feedback_str}</div>'
        )

        # OOB: restore button label
        btn_oob = (
            '<span id="auto-fix-btn-content" hx-swap-oob="true"'
            ' class="text-green-600 font-bold">✓ 完了</span>'
        )

        return HTMLResponse(content=btn_oob + feedback_oob + body)

    except Exception as e:
        import traceback
        logger.error(f"Auto-fix failed:\n{traceback.format_exc()}")
        # OOB swap the button content so the error is visible even with hx-swap="none"
        return HTMLResponse(
            content=f'<span id="auto-fix-btn-content" hx-swap-oob="true"'
            f' class="text-red-500 text-xs">エラー: {str(e)}</span>'
        )

# (Legacy Phase 2 reconstruction routes removed — pipeline is now unified)
