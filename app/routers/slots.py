"""Slot editing routes - update slot values and re-render previews."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
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

    # Persist to session regardless (so the user doesn't lose input)
    session_slots = _get_session_slots(request, pattern_id)
    slot_type = form_data.get("slot_type", "text")
    if slot_type == "button":
        session_slots[slot_id] = {
            "label": str(value),
            "bg_color": form_data.get("bg_color", slot.bg_color or "#333333"),
            "text_color": form_data.get("text_color", slot.text_color or "#ffffff"),
        }
    elif slot_type == "image":
        prompt = form_data.get("prompt", "")
        session_slots[slot_id] = {
            "source_url": str(value),
            "prompt": str(prompt) if prompt else "",
            "fit": form_data.get("fit", "cover"),
        }
    else:
        session_slots[slot_id] = str(value)
    _set_session_slots(request, pattern_id, session_slots)

    # Re-render SVG preview with current slot values
    svg_markup = svg_renderer.render(template, session_slots)

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
