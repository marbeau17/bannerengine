"""Slot validation service for banner templates."""

from __future__ import annotations

import re
from urllib.parse import urlparse

from app.models.template import BannerTemplate, Slot, SlotType


class SlotService:
    """Service for validating slot values against template slot definitions."""

    def validate_slot_value(self, slot: Slot, value: dict) -> list[str]:
        """Validate a single slot value against its slot definition.

        Args:
            slot: The slot definition from the template.
            value: The slot value dict provided by the user.

        Returns:
            A list of error messages. Empty list means valid.
        """
        errors: list[str] = []

        # Required check - if value is empty or has no meaningful content
        if slot.required and not value:
            errors.append(f"Slot '{slot.id}' is required.")
            return errors

        if not value:
            return errors

        slot_type = slot.type

        if slot_type == SlotType.TEXT:
            errors.extend(self._validate_text(slot, value))
        elif slot_type == SlotType.IMAGE:
            errors.extend(self._validate_image(slot, value))
        elif slot_type == SlotType.BUTTON:
            errors.extend(self._validate_button(slot, value))
        elif slot_type == SlotType.IMAGE_OR_TEXT:
            # Accept either image or text content
            has_text = bool(value.get("text"))
            has_image = bool(value.get("image_url"))
            if slot.required and not has_text and not has_image:
                errors.append(
                    f"Slot '{slot.id}' requires either text or image content."
                )
            if has_text:
                errors.extend(self._validate_text(slot, value))
            if has_image:
                errors.extend(self._validate_image(slot, value))

        return errors

    def validate_all_slots(
        self, template: BannerTemplate, slot_values: dict
    ) -> dict[str, list[str]]:
        """Validate all slot values against a banner template.

        Args:
            template: The banner template with slot definitions.
            slot_values: Dict mapping slot_id to value dicts.

        Returns:
            Dict mapping slot_id to a list of error messages.
            Only slots with errors are included.
        """
        all_errors: dict[str, list[str]] = {}

        for slot in template.slots:
            value = slot_values.get(slot.id, {})
            errors = self.validate_slot_value(slot, value)
            if errors:
                all_errors[slot.id] = errors

        return all_errors

    # ------------------------------------------------------------------
    # Private validation helpers
    # ------------------------------------------------------------------

    def _validate_text(self, slot: Slot, value: dict) -> list[str]:
        """Validate text-specific constraints."""
        errors: list[str] = []
        text = value.get("text", "")

        if slot.required and not text.strip():
            errors.append(f"Slot '{slot.id}' requires non-empty text.")
            return errors

        if slot.max_chars is not None and len(text) > slot.max_chars:
            errors.append(
                f"Slot '{slot.id}' text exceeds maximum length of "
                f"{slot.max_chars} characters (got {len(text)})."
            )

        return errors

    def _validate_image(self, slot: Slot, value: dict) -> list[str]:
        """Validate image-specific constraints."""
        errors: list[str] = []
        image_url = value.get("image_url", "")

        if slot.required and not image_url.strip():
            errors.append(f"Slot '{slot.id}' requires an image URL.")
            return errors

        if image_url:
            # Check format hint if present
            if slot.format_hint:
                allowed_formats = [
                    fmt.strip().lower() for fmt in slot.format_hint.split(",")
                ]
                # Extract extension from URL path
                parsed = urlparse(image_url)
                path_lower = parsed.path.lower()
                if not any(path_lower.endswith(f".{fmt}") for fmt in allowed_formats):
                    errors.append(
                        f"Slot '{slot.id}' image format should be one of: "
                        f"{slot.format_hint}."
                    )

        return errors

    def _validate_button(self, slot: Slot, value: dict) -> list[str]:
        """Validate button-specific constraints."""
        errors: list[str] = []
        label = value.get("label", "")
        link_url = value.get("link_url", "")

        if slot.required and not label.strip():
            errors.append(f"Slot '{slot.id}' requires a button label.")

        if slot.max_chars is not None and len(label) > slot.max_chars:
            errors.append(
                f"Slot '{slot.id}' label exceeds maximum length of "
                f"{slot.max_chars} characters (got {len(label)})."
            )

        if link_url:
            errors.extend(self._validate_url(slot.id, link_url))

        return errors

    def _validate_url(self, slot_id: str, url: str) -> list[str]:
        """Validate a URL value, rejecting dangerous schemes."""
        errors: list[str] = []

        # Reject javascript: and data: schemes
        url_stripped = url.strip().lower()
        dangerous_schemes = ("javascript:", "data:", "vbscript:")
        if any(url_stripped.startswith(scheme) for scheme in dangerous_schemes):
            errors.append(
                f"Slot '{slot_id}' contains a disallowed URL scheme. "
                "Only http and https URLs are permitted."
            )
            return errors

        # Basic URL structure validation
        try:
            parsed = urlparse(url)
            if parsed.scheme and parsed.scheme not in ("http", "https", ""):
                errors.append(
                    f"Slot '{slot_id}' URL has an unsupported scheme: "
                    f"'{parsed.scheme}'. Use http or https."
                )
            # Relative URLs are acceptable (no scheme), but if a scheme is
            # present we expect a netloc
            if parsed.scheme and not parsed.netloc:
                errors.append(
                    f"Slot '{slot_id}' URL appears malformed (missing host)."
                )
        except Exception:
            errors.append(f"Slot '{slot_id}' contains an invalid URL.")

        return errors
