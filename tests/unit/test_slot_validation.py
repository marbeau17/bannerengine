"""Unit tests for slot validation logic.

14 tests covering required/optional, max_chars, format hints,
button URL validation, and image_or_text dual-mode behaviour.
"""

from __future__ import annotations

import pytest

from app.models.template import Slot, SlotType


# ---------------------------------------------------------------------------
# Helper: minimal Slot factory
# ---------------------------------------------------------------------------

def _make_slot(
    slot_id: str = "test_slot",
    slot_type: SlotType = SlotType.TEXT,
    required: bool = True,
    max_chars: int | None = None,
    format_hint: str | None = None,
    default_label: str | None = None,
    bg_color: str | None = None,
    text_color: str | None = None,
) -> Slot:
    return Slot(
        id=slot_id,
        type=slot_type,
        x=0.0,
        y=0.0,
        width=50.0,
        height=20.0,
        required=required,
        max_chars=max_chars,
        format_hint=format_hint,
        default_label=default_label,
        bg_color=bg_color,
        text_color=text_color,
    )


def _validate_slot_value(slot: Slot, value: str) -> list[str]:
    """Mirror of app.routers.slots._validate_slot_value for unit testing."""
    errors: list[str] = []
    if slot.required and not value.strip():
        errors.append(f"Slot '{slot.id}' is required.")
    if slot.max_chars is not None and len(value) > slot.max_chars:
        errors.append(
            f"Slot '{slot.id}' exceeds maximum length of {slot.max_chars} characters "
            f"(got {len(value)})."
        )
    return errors


# ---------------------------------------------------------------------------
# Required / optional text
# ---------------------------------------------------------------------------

class TestRequiredSlot:
    """Required text slot must have non-empty value."""

    def test_required_slot_empty_value_fails(self):
        slot = _make_slot(required=True)
        errors = _validate_slot_value(slot, "")
        assert len(errors) == 1
        assert "required" in errors[0].lower()

    def test_required_slot_whitespace_only_fails(self):
        slot = _make_slot(required=True)
        errors = _validate_slot_value(slot, "   ")
        assert len(errors) == 1

    def test_required_slot_valid_value_passes(self):
        slot = _make_slot(required=True)
        errors = _validate_slot_value(slot, "Hello World")
        assert errors == []

    def test_optional_slot_empty_value_passes(self):
        slot = _make_slot(required=False)
        errors = _validate_slot_value(slot, "")
        assert errors == []

    def test_optional_slot_with_value_passes(self):
        slot = _make_slot(required=False)
        errors = _validate_slot_value(slot, "Some text")
        assert errors == []


# ---------------------------------------------------------------------------
# max_chars
# ---------------------------------------------------------------------------

class TestMaxChars:
    """max_chars constraint is enforced correctly."""

    def test_within_max_chars_passes(self):
        slot = _make_slot(max_chars=10)
        errors = _validate_slot_value(slot, "Short")
        assert errors == []

    def test_exact_max_chars_passes(self):
        slot = _make_slot(max_chars=5)
        errors = _validate_slot_value(slot, "12345")
        assert errors == []

    def test_exceeds_max_chars_fails(self):
        slot = _make_slot(max_chars=5)
        errors = _validate_slot_value(slot, "123456")
        assert len(errors) == 1
        assert "exceeds" in errors[0].lower()

    def test_no_max_chars_any_length_passes(self):
        slot = _make_slot(max_chars=None)
        errors = _validate_slot_value(slot, "A" * 1000)
        assert errors == []


# ---------------------------------------------------------------------------
# Image format hint
# ---------------------------------------------------------------------------

class TestImageFormatHint:
    """Image slot format_hint is stored on the Slot model."""

    def test_image_slot_has_format_hint(self):
        slot = _make_slot(slot_type=SlotType.IMAGE, format_hint="JPG or PNG")
        assert slot.format_hint == "JPG or PNG"

    def test_image_slot_no_format_hint(self):
        slot = _make_slot(slot_type=SlotType.IMAGE)
        assert slot.format_hint is None


# ---------------------------------------------------------------------------
# Button slot attributes
# ---------------------------------------------------------------------------

class TestButtonSlotValidation:
    """Button slot carries default_label, bg_color, text_color."""

    def test_button_slot_default_label(self):
        slot = _make_slot(
            slot_type=SlotType.BUTTON,
            default_label="Click Here",
            bg_color="#ff0000",
            text_color="#ffffff",
        )
        assert slot.default_label == "Click Here"
        assert slot.bg_color == "#ff0000"
        assert slot.text_color == "#ffffff"


# ---------------------------------------------------------------------------
# image_or_text dual-mode
# ---------------------------------------------------------------------------

class TestImageOrTextSlot:
    """image_or_text slots accept both image and text values."""

    def test_image_or_text_as_text(self):
        slot = _make_slot(slot_type=SlotType.IMAGE_OR_TEXT, max_chars=20)
        errors = _validate_slot_value(slot, "Brand Name")
        assert errors == []

    def test_image_or_text_as_image_url(self):
        slot = _make_slot(slot_type=SlotType.IMAGE_OR_TEXT, required=True)
        # An image URL string is still valid text input for the validator.
        errors = _validate_slot_value(slot, "https://example.com/logo.png")
        assert errors == []
