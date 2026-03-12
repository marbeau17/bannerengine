"""XML template parser using defusedxml for safe parsing."""

from __future__ import annotations

import os
from xml.etree.ElementTree import Element

import defusedxml.ElementTree as ET

from app.core.exceptions import XMLParseError, UnknownSlotTypeError
from app.models.template import (
    BannerTemplate,
    Slot,
    SlotType,
    TemplateDesign,
    TemplateMeta,
)

_VALID_SLOT_TYPES = {e.value for e in SlotType}


class XMLTemplateParser:
    """Parser for banner template XML files."""

    def parse_file(self, file_path: str) -> list[BannerTemplate]:
        """Parse an XML template file and return a list of BannerTemplates.

        The file may contain a single ``<banner_template>`` root or a
        ``<banner_templates>`` root wrapping multiple ``<banner_template>``
        children.

        Args:
            file_path: Absolute or relative path to the XML file.

        Returns:
            A list of BannerTemplate instances.

        Raises:
            XMLParseError: If the file cannot be read or the XML is malformed.
        """
        if not os.path.isfile(file_path):
            raise XMLParseError(f"File not found: {file_path}")

        try:
            tree = ET.parse(file_path)
            root = tree.getroot()
        except Exception as exc:
            raise XMLParseError(f"Failed to parse XML file '{file_path}': {exc}") from exc

        return self._parse_root(root)

    def parse_string(self, xml_string: str) -> list[BannerTemplate]:
        """Parse an XML string and return a list of BannerTemplates.

        Args:
            xml_string: Raw XML content as a string.

        Returns:
            A list of BannerTemplate instances.

        Raises:
            XMLParseError: If the XML string is malformed.
        """
        try:
            root = ET.fromstring(xml_string)
        except Exception as exc:
            raise XMLParseError(f"Failed to parse XML string: {exc}") from exc

        return self._parse_root(root)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _parse_root(self, root: Element) -> list[BannerTemplate]:
        """Handle both single and multi-template XML files.

        If the root tag is ``banner_templates`` (plural), iterate over its
        ``banner_template`` children.  Otherwise treat the root itself as a
        single template element.
        """
        tag = root.tag.lower().replace("-", "_")
        if tag == "banner_templates":
            children = root.findall("banner_template")
            if not children:
                return [self._build_template(root)]
            return [self._build_template(child) for child in children]
        return [self._build_template(root)]

    def _build_template(self, root: Element) -> BannerTemplate:
        """Build a BannerTemplate from the parsed XML root element."""
        meta_elem = root.find("meta")
        if meta_elem is None:
            raise XMLParseError("Missing <meta> section in template XML")

        design_elem = root.find("design")
        if design_elem is None:
            raise XMLParseError("Missing <design> section in template XML")

        slots_elem = root.find("slots")
        rules_elem = root.find("rules")

        meta = self._parse_meta(meta_elem)
        design = self._parse_design(design_elem)
        slots = self._parse_slots(slots_elem) if slots_elem is not None else []
        rules = self._parse_rules(rules_elem) if rules_elem is not None else []

        return BannerTemplate(meta=meta, design=design, slots=slots, rules=rules)

    def _parse_meta(self, meta_elem: Element) -> TemplateMeta:
        """Parse the <meta> section of the template XML."""
        def _text(tag: str, default: str = "") -> str:
            child = meta_elem.find(tag)
            return child.text.strip() if child is not None and child.text else default

        try:
            return TemplateMeta(
                category=_text("category"),
                pattern_id=_text("pattern_id"),
                pattern_name=_text("pattern_name"),
                width=int(_text("width", "0")),
                height=int(_text("height", "0")),
                unit=_text("unit", "px"),
                aspect_ratio=_text("aspect_ratio"),
                layout_type=_text("layout_type"),
                recommended_use=_text("recommended_use"),
            )
        except (ValueError, TypeError) as exc:
            raise XMLParseError(f"Invalid meta values: {exc}") from exc

    def _parse_design(self, design_elem: Element) -> TemplateDesign:
        """Parse the <design> section of the template XML."""
        def _text(tag: str, default: str | None = None) -> str | None:
            child = design_elem.find(tag)
            if child is not None and child.text:
                return child.text.strip()
            return default

        def _float_or_none(tag: str) -> float | None:
            val = _text(tag)
            if val is not None:
                try:
                    return float(val)
                except ValueError:
                    return None
            return None

        return TemplateDesign(
            background_type=_text("background_type", ""),
            background_value=_text("background_value"),
            overlay_type=_text("overlay_type"),
            overlay_opacity=_float_or_none("overlay_opacity"),
            primary_color=_text("primary_color", ""),
            accent_color=_text("accent_color"),
            font_style=_text("font_style", ""),
            highlight_panel=_text("highlight_panel"),
            illustration_style=_text("illustration_style"),
        )

    def _parse_slots(self, slots_elem: Element) -> list[Slot]:
        """Parse all <slot> children inside the <slots> section."""
        slots: list[Slot] = []
        for slot_elem in slots_elem.findall("slot"):
            slots.append(self._parse_slot(slot_elem))
        return slots

    def _parse_slot(self, slot_elem: Element) -> Slot:
        """Parse an individual <slot> element with type detection.

        Handles percentage coordinate values by stripping the '%' sign
        and converting to float.

        Raises:
            UnknownSlotTypeError: If the slot type is not recognized.
        """
        def _text(tag: str, default: str = "") -> str:
            child = slot_elem.find(tag)
            return child.text.strip() if child is not None and child.text else default

        def _attr(name: str, default: str = "") -> str:
            return slot_elem.get(name, default)

        def _parse_coordinate(value: str) -> float:
            """Strip '%' suffix and convert to float."""
            cleaned = value.strip().rstrip("%").strip()
            try:
                return float(cleaned)
            except ValueError:
                return 0.0

        # Type detection
        slot_type_str = _text("type") or _attr("type")
        if slot_type_str not in _VALID_SLOT_TYPES:
            raise UnknownSlotTypeError(slot_type_str)

        # Required boolean
        required_str = _text("required", "true")
        required = required_str.lower() not in ("false", "0", "no")

        # Integer or None helper
        def _int_or_none(tag: str) -> int | None:
            val = _text(tag)
            if val:
                try:
                    return int(val)
                except ValueError:
                    return None
            return None

        return Slot(
            id=_text("id") or _attr("id"),
            type=SlotType(slot_type_str),
            x=_parse_coordinate(_text("x", "0")),
            y=_parse_coordinate(_text("y", "0")),
            width=_parse_coordinate(_text("width", "0")),
            height=_parse_coordinate(_text("height", "0")),
            description=_text("description"),
            required=required,
            max_chars=_int_or_none("max_chars"),
            font_size_guideline=_text("font_size_guideline") or None,
            font_weight=_text("font_weight") or None,
            color=_text("color") or None,
            default_label=_text("default_label") or None,
            bg_color=_text("bg_color") or None,
            text_color=_text("text_color") or None,
            format_hint=_text("format_hint") or None,
        )

    def _parse_rules(self, rules_elem: Element) -> list[str]:
        """Parse the <rules> section, returning a list of rule strings."""
        rules: list[str] = []
        for rule_elem in rules_elem.findall("rule"):
            if rule_elem.text and rule_elem.text.strip():
                rules.append(rule_elem.text.strip())
        return rules
