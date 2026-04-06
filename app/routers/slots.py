"""Slot editing routes - update slot values and re-render previews."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates

from app.core.exceptions import TemplateNotFoundError, ValidationError

router = APIRouter(prefix="/api/slots", tags=["slots"])

templates = Jinja2Templates(directory="app/templates")


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def _validate_slot_value(slot, value: str) -> list[str]:
    """Validate a slot value against the slot's rules.

    Returns a list of error messages (empty if valid).
    """
    errors: list[str] = []

    if slot.required and not value.strip():
        errors.append(f"Slot '{slot.id}' is required.")

    if slot.max_chars is not None and len(value) > slot.max_chars:
        errors.append(
            f"Slot '{slot.id}' exceeds maximum length of {slot.max_chars} characters "
            f"(got {len(value)})."
        )

    return errors


def _get_session_slots(request: Request, pattern_id: str) -> dict[str, Any]:
    """Retrieve the current slot values dict from the session."""
    return request.session.get(f"slots_{pattern_id}", {})


def _set_session_slots(
    request: Request, pattern_id: str, slots: dict[str, Any]
) -> None:
    """Persist slot values dict into the session."""
    request.session[f"slots_{pattern_id}"] = slots


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.patch("/order/{pattern_id}", response_class=HTMLResponse)
async def update_slot_order(request: Request, pattern_id: str):
    """Persist the drag-reordered layer sequence and return a re-rendered canvas.

    Accepts JSON: ``{"order": ["slot_id_1", "slot_id_2", ...]}``
    The SVG renderer reads ``_order`` from the session and draws slots in
    that sequence, controlling which elements appear in front of others.
    Returns the updated preview_canvas.html partial so the browser can
    swap the canvas in-place without a full page reload.
    """
    template_service = request.app.state.template_service
    svg_renderer = request.app.state.svg_renderer
    template = template_service.get_template(pattern_id)

    body = await request.json()
    order = body.get("order", [])
    session_slots = _get_session_slots(request, pattern_id)
    session_slots["_order"] = [str(sid) for sid in order]
    _set_session_slots(request, pattern_id, session_slots)

    # Apply any design overrides before rendering
    effective_template = template
    design_overrides = session_slots.get("_design")
    if isinstance(design_overrides, dict) and design_overrides.get("background_value"):
        effective_template = template.model_copy(deep=True)
        effective_template.design.background_value = design_overrides["background_value"]

    svg_markup = svg_renderer.render(effective_template, session_slots)
    return templates.TemplateResponse(
        request,
        "partials/preview_canvas.html",
        {"template": effective_template, "pattern_id": pattern_id, "svg_markup": svg_markup},
    )


@router.post("/{pattern_id}/reset")
async def reset_slots(request: Request, pattern_id: str):
    """Wipe all session overrides for a template and trigger a full page reload.

    Clears:
    - ``slots_{pattern_id}``  — all text, position, AI-generated values
    - ``custom_ref_{pattern_id}`` — any custom uploaded reference image

    Returns an empty 204 response with ``HX-Refresh: true`` so HTMX performs
    a hard reload, cleanly resetting all frontend state (lock states, inputs, etc.)
    without any extra JavaScript.
    """
    request.session.pop(f"slots_{pattern_id}", None)
    request.session.pop(f"custom_ref_{pattern_id}", None)
    return Response(status_code=204, headers={"HX-Refresh": "true"})


@router.delete("/{pattern_id}/{slot_id}", response_class=HTMLResponse)
async def hide_slot(request: Request, pattern_id: str, slot_id: str):
    """Soft-delete a template slot by writing ``_hidden: True`` to its session value.

    Template slots come from the read-only XML file and cannot be permanently
    removed, so we hide them instead.  The SVG renderer and sidebar both check
    this flag and skip any slot that carries it.  A full reset (POST .../reset)
    wipes the session entirely, implicitly restoring all hidden slots.
    """
    template_service = request.app.state.template_service
    svg_renderer = request.app.state.svg_renderer
    template = template_service.get_template(pattern_id)

    session_slots = _get_session_slots(request, pattern_id)
    existing = session_slots.get(slot_id, {})
    if not isinstance(existing, dict):
        existing = {}
    existing["_hidden"] = True
    session_slots[slot_id] = existing
    _set_session_slots(request, pattern_id, session_slots)

    effective_template = template
    design_overrides = session_slots.get("_design")
    if isinstance(design_overrides, dict) and design_overrides.get("background_value"):
        effective_template = template.model_copy(deep=True)
        effective_template.design.background_value = design_overrides["background_value"]

    svg_markup = svg_renderer.render(effective_template, session_slots)

    from app.routers.pages import _build_sidebar_layers
    canvas_html = templates.env.get_template("partials/preview_canvas.html").render(
        request=request,
        template=effective_template,
        pattern_id=pattern_id,
        svg_markup=svg_markup,
    )
    sidebar_layers, _ = _build_sidebar_layers(effective_template, session_slots)
    sidebar_html = templates.env.get_template("partials/layer_sidebar.html").render(
        request=request,
        sidebar_layers=sidebar_layers,
        pattern_id=pattern_id,
    )
    return HTMLResponse(content=canvas_html + sidebar_html)


@router.patch("/{pattern_id}/{slot_id}", response_class=HTMLResponse)
async def update_slot(request: Request, pattern_id: str, slot_id: str):
    """Update a single slot value (htmx form submission).

    Accepts form data, validates the value against template rules,
    stores the result in the session, re-renders the SVG preview,
    and returns the updated preview canvas partial.  Validation
    errors are returned as an out-of-band (OOB) swap.
    """
    template_service = request.app.state.template_service
    svg_renderer = request.app.state.svg_renderer
    template = template_service.get_template(pattern_id)



    # Handle design property updates (pseudo-slot "_design")
    if slot_id == "_design":
        form_data = await request.form()
        session_slots = _get_session_slots(request, pattern_id)
        design = session_slots.get("_design", {})
        if not isinstance(design, dict):
            design = {}
        bg = form_data.get("content", form_data.get("value", ""))
        if bg:
            design["background_value"] = str(bg)
        session_slots["_design"] = design
        _set_session_slots(request, pattern_id, session_slots)

        # Apply design override to template for rendering
        effective_template = template.model_copy(deep=True)
        if design.get("background_value"):
            effective_template.design.background_value = design["background_value"]

        svg_markup = svg_renderer.render(effective_template, session_slots)
        return templates.TemplateResponse(
            request,
            "partials/preview_canvas.html",
            {"template": effective_template, "pattern_id": pattern_id, "svg_markup": svg_markup},
        )

    # Find the target slot definition
    slot = next((s for s in template.slots if s.id == slot_id), None)
    if slot is None:
        raise ValidationError(
            message=f"Slot '{slot_id}' not found in template '{pattern_id}'.",
            errors=[f"Unknown slot: {slot_id}"],
        )

    # Parse form data sent by htmx
    form_data = await request.form()
    value = form_data.get("content", form_data.get("value", ""))

    # Validate
    validation_errors = _validate_slot_value(slot, str(value))

    # Persist to session using merge logic (so changing one property doesn't clobber others)
    session_slots = _get_session_slots(request, pattern_id)
    existing = session_slots.get(slot_id, {})
    if isinstance(existing, str):
        existing = {"text": existing}  # migrate legacy string format

    slot_type = form_data.get("slot_type", "text")

    # Merge content field
    if value:
        if slot_type == "button":
            existing["label"] = str(value)
        elif slot_type == "image":
            existing["source_url"] = str(value)
        else:
            existing["text"] = str(value)

    # Merge type-specific fields (only if present in form data)
    _MERGE_FIELDS = {
        "button": ("bg_color", "text_color", "font_size"),
        "image": ("prompt", "fit"),
        "text": ("font_size", "font_weight", "color"),
    }
    for field in _MERGE_FIELDS.get(slot_type, ()):
        form_val = form_data.get(field)
        if form_val is not None:
            existing[field] = str(form_val)

    # Merge opacity (slider sends 0-100, store as 0.0-1.0 float)
    opacity_val = form_data.get("opacity")
    if opacity_val is not None and str(opacity_val).strip():
        try:
            existing["opacity"] = round(max(0.0, min(100.0, float(opacity_val))) / 100.0, 2)
        except (ValueError, TypeError):
            pass

    # Merge position/size overrides (px → % conversion)
    canvas_w = template.meta.width
    canvas_h = template.meta.height
    px_to_pct = {
        "x_px": ("x", canvas_w), "y_px": ("y", canvas_h),
        "width_px": ("width", canvas_w), "height_px": ("height", canvas_h),
    }
    for px_field, (pct_field, canvas_dim) in px_to_pct.items():
        form_val = form_data.get(px_field)
        if form_val is not None and str(form_val).strip():
            existing[pct_field] = str(round(float(form_val) / canvas_dim * 100, 2))
    # Also accept raw % values (backward compat)
    for field in ("x", "y", "width", "height"):
        form_val = form_data.get(field)
        if form_val is not None and str(form_val).strip():
            existing[field] = str(form_val)

    session_slots[slot_id] = existing
    _set_session_slots(request, pattern_id, session_slots)

    # Apply design overrides if present
    effective_template = template
    design_overrides = session_slots.get("_design")
    if isinstance(design_overrides, dict) and design_overrides.get("background_value"):
        effective_template = template.model_copy(deep=True)
        effective_template.design.background_value = design_overrides["background_value"]

    # Re-render SVG preview with current slot values
    svg_markup = svg_renderer.render(effective_template, session_slots)

    return templates.TemplateResponse(
        request,
        "partials/preview_canvas.html",
        {
            "template": template,
            "pattern_id": pattern_id,
            "svg_markup": svg_markup,
            "slot_id": slot_id,
            "validation_errors": validation_errors,
        },
    )


@router.patch("/{pattern_id}/{slot_id}/position", response_class=HTMLResponse)
async def update_slot_position(request: Request, pattern_id: str, slot_id: str):
    """Silently update position and/or size of a slot (drag-and-drop / resize sync).

    Accepts any combination of percentage-based x, y, width, height fields,
    saves them to the session, and returns a re-rendered preview canvas partial.
    At least one field must be provided.
    """
    template_service = request.app.state.template_service
    svg_renderer = request.app.state.svg_renderer
    template = template_service.get_template(pattern_id)

    form_data = await request.form()
    fields = {k: form_data.get(k) for k in ("x", "y", "width", "height")}
    provided = {k: v for k, v in fields.items() if v is not None}

    if not provided:
        raise ValidationError(message="At least one of x, y, width, height is required.", errors=["No fields provided"])

    try:
        parsed = {k: str(round(float(v), 4)) for k, v in provided.items()}
    except (ValueError, TypeError):
        raise ValidationError(message="All geometry fields must be numeric.", errors=["Invalid value"])

    session_slots = _get_session_slots(request, pattern_id)
    existing = session_slots.get(slot_id, {})
    if not isinstance(existing, dict):
        existing = {}
    existing.update(parsed)
    session_slots[slot_id] = existing
    _set_session_slots(request, pattern_id, session_slots)

    effective_template = template
    design_overrides = session_slots.get("_design")
    if isinstance(design_overrides, dict) and design_overrides.get("background_value"):
        effective_template = template.model_copy(deep=True)
        effective_template.design.background_value = design_overrides["background_value"]

    svg_markup = svg_renderer.render(effective_template, session_slots)
    return templates.TemplateResponse(
        request,
        "partials/preview_canvas.html",
        {"template": effective_template, "pattern_id": pattern_id, "svg_markup": svg_markup},
    )


@router.put("/{pattern_id}")
async def save_all_slots(request: Request, pattern_id: str):
    """Save all slot values at once (JSON body).

    Accepts a JSON object mapping slot IDs to their value dicts,
    validates each one, and persists the full set to the session.
    """
    template_service = request.app.state.template_service
    template = template_service.get_template(pattern_id)



    body: dict[str, Any] = await request.json()
    all_errors: list[str] = []
    slot_map = {s.id: s for s in template.slots}

    # Build the values dict, validating as we go
    session_slots: dict[str, Any] = {}
    for sid, val in body.items():
        value_str = val if isinstance(val, str) else val.get("value", "")
        session_slots[sid] = {"value": value_str}

        slot_def = slot_map.get(sid)
        if slot_def:
            errors = _validate_slot_value(slot_def, value_str)
            all_errors.extend(errors)

    if all_errors:
        raise ValidationError(
            message="One or more slot values failed validation.",
            errors=all_errors,
        )

    _set_session_slots(request, pattern_id, session_slots)

    return {"status": "ok", "pattern_id": pattern_id, "saved": len(session_slots)}


@router.get("/{pattern_id}/{slot_id}")
async def get_slot_value(request: Request, pattern_id: str, slot_id: str):
    """Return the current value for a single slot from the session."""
    template_service = request.app.state.template_service
    template = template_service.get_template(pattern_id)



    session_slots = _get_session_slots(request, pattern_id)
    slot_value = session_slots.get(slot_id, {})

    return {"pattern_id": pattern_id, "slot_id": slot_id, "value": slot_value}
