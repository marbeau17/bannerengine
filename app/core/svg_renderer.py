"""Server-side SVG generation for banner templates."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any

from app.core.exceptions import GenerationError
from app.models.template import BannerTemplate, Slot, SlotType, TemplateDesign


_DEFAULT_FONT_FAMILY = "Hiragino Kaku Gothic ProN, Hiragino Sans, Yu Gothic, Arial, Apple Color Emoji, sans-serif"


class SvgRenderer:
    """Renders a BannerTemplate with slot values into an SVG string."""

    def render(self, template: BannerTemplate, slot_values: dict[str, Any]) -> str:
        """Generate a complete SVG string for the given template and values."""
        try:
            width = template.meta.width
            height = template.meta.height

            svg = ET.Element("svg", attrib={
                "xmlns": "http://www.w3.org/2000/svg",
                "xmlns:xlink": "http://www.w3.org/1999/xlink",
                "viewBox": f"0 0 {width} {height}",
                "width": str(width),
                "height": str(height),
            })

            self._defs = ET.SubElement(svg, "defs")
            self._render_background(svg, template.design, width, height)

            for slot in template.slots:
                value = slot_values.get(slot.id)
                self._render_slot(svg, slot, value, template)

            return ET.tostring(svg, encoding="unicode", xml_declaration=False)
        except GenerationError:
            raise
        except Exception as exc:
            raise GenerationError(f"SVG rendering failed: {exc}") from exc

    def _render_background(self, svg: ET.Element, design: TemplateDesign, w: int, h: int) -> None:
        bg_group = ET.SubElement(svg, "g", attrib={"id": "Background", "data-name": "Background"})
        bg_type = (design.background_type or "").lower()
        bg_value = design.background_value or design.primary_color

        if bg_type == "gradient" and bg_value:
            parts = [p.strip() for p in bg_value.split(",")]
            if len(parts) >= 2:
                grad = ET.SubElement(self._defs, "linearGradient",
                                     attrib={"id": "bg-grad", "x1": "0%", "y1": "0%", "x2": "100%", "y2": "100%"})
                ET.SubElement(grad, "stop", attrib={"offset": "0%", "stop-color": parts[0]})
                ET.SubElement(grad, "stop", attrib={"offset": "100%", "stop-color": parts[1]})
                ET.SubElement(bg_group, "rect", attrib={"x": "0", "y": "0", "width": str(w), "height": str(h), "fill": "url(#bg-grad)"})
            else:
                ET.SubElement(bg_group, "rect", attrib={"x": "0", "y": "0", "width": str(w), "height": str(h), "fill": parts[0]})
        elif bg_type == "image" and bg_value:
            ET.SubElement(bg_group, "image", attrib={
                "href": bg_value, "x": "0", "y": "0",
                "width": str(w), "height": str(h), "preserveAspectRatio": "xMidYMid slice",
            })
        else:
            fill = bg_value if bg_value else "#ffffff"
            ET.SubElement(bg_group, "rect", attrib={"x": "0", "y": "0", "width": str(w), "height": str(h), "fill": fill})

    @staticmethod
    def _effective_geometry(slot: Slot, value: Any) -> tuple[float, float, float, float]:
        """Return (x%, y%, width%, height%) using session overrides if present."""
        if isinstance(value, dict):
            x = float(value["x"]) if value.get("x") else slot.x
            y = float(value["y"]) if value.get("y") else slot.y
            w = float(value["width"]) if value.get("width") else slot.width
            h = float(value["height"]) if value.get("height") else slot.height
            return (x, y, w, h)
        return (slot.x, slot.y, slot.width, slot.height)

    def _render_slot(self, svg: ET.Element, slot: Slot, value: Any, template: BannerTemplate) -> None:
        w, h = template.meta.width, template.meta.height

        x_pct, y_pct, w_pct, h_pct = self._effective_geometry(slot, value)
        slot_group = ET.SubElement(svg, "g", attrib={
            "id": slot.id,
            "data-name": slot.id,
            "class": "draggable-slot",
            "data-slot-id": slot.id,
            "data-slot-type": slot.type.value,
            "data-x": f"{x_pct:.4f}",
            "data-y": f"{y_pct:.4f}",
            "data-w": f"{w_pct:.4f}",
            "data-h": f"{h_pct:.4f}",
        })
        normalised = self._normalise_value(slot, value)

        # Check for AI prompt with no image yet
        prompt_text = self._extract_prompt(value)
        if prompt_text and not self._has_image_url(value) and (normalised is None or normalised == ""):
            self._render_prompt_placeholder(slot_group, slot, value, prompt_text, w, h)
            return

        if normalised is None or normalised == "":
            self._render_placeholder(slot_group, slot, value, w, h)
            return

        if slot.type in (SlotType.TEXT, SlotType.IMAGE_OR_TEXT):
            if slot.type == SlotType.IMAGE_OR_TEXT and isinstance(value, dict) and value.get("slot_type") == "image":
                self._render_image_slot(slot_group, slot, value, normalised, w, h)
            else:
                self._render_text_slot(slot_group, slot, value, normalised, w, h)
        elif slot.type == SlotType.IMAGE:
            self._render_image_slot(slot_group, slot, value, normalised, w, h)
        elif slot.type == SlotType.BUTTON:
            self._render_button_slot(slot_group, slot, value, normalised, w, h)
        else:
            self._render_text_slot(slot_group, slot, value, str(normalised), w, h)

    @staticmethod
    def _normalise_value(slot: Slot, value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, str):
            return value
        if isinstance(value, dict):
            if slot.type == SlotType.IMAGE_OR_TEXT and value.get("slot_type") == "image":
                return value.get("source_url", value.get("image_url", ""))
            if slot.type in (SlotType.TEXT, SlotType.IMAGE_OR_TEXT):
                return value.get("text", value.get("content", value.get("label", value.get("value", ""))))
            if slot.type == SlotType.IMAGE:
                return value.get("source_url", value.get("image_url", ""))
            if slot.type == SlotType.BUTTON:
                return value
            return str(value)
        for attr in ("text", "image_url", "label"):
            if hasattr(value, attr):
                return getattr(value, attr)
        return str(value)

    @staticmethod
    def _extract_font_props(slot: Slot, raw_value: Any) -> tuple[str, str, str]:
        """Extract (font_size_num, font_weight, color) from session overrides or slot defaults."""
        fs = (raw_value.get("font_size") if isinstance(raw_value, dict) else None) or slot.font_size_guideline or "16"
        fs_num = "".join(c for c in str(fs) if c.isdigit() or c == ".") or "16"
        fw = (raw_value.get("font_weight") if isinstance(raw_value, dict) else None) or slot.font_weight or "normal"
        clr = (raw_value.get("color") if isinstance(raw_value, dict) else None) or slot.color or "#000000"
        return fs_num, fw, clr

    def _render_text_slot(self, svg: ET.Element, slot: Slot, raw_value: Any, value: str, w: int, h: int) -> None:
        sx, sy, swidth, sheight = self._effective_geometry(slot, raw_value)
        x, y = self._calc_px(sx, w), self._calc_px(sy, h)
        sw, sh = self._calc_px(swidth, w), self._calc_px(sheight, h)

        font_size_num, font_weight, color = self._extract_font_props(slot, raw_value)

        text_elem = ET.SubElement(svg, "text", attrib={
            "x": f"{x + sw / 2:.1f}", "y": f"{y + sh / 2:.1f}",
            "font-family": _DEFAULT_FONT_FAMILY,
            "font-size": font_size_num,
            "font-weight": font_weight,
            "fill": color,
            "text-anchor": "middle", "dominant-baseline": "central",
            "data-content": "true",
        })
        text_elem.text = str(value)

    def _render_image_slot(self, svg: ET.Element, slot: Slot, raw_value: Any, value: str, w: int, h: int) -> None:
        sx, sy, swidth, sheight = self._effective_geometry(slot, raw_value)
        x, y = self._calc_px(sx, w), self._calc_px(sy, h)
        sw, sh = self._calc_px(swidth, w), self._calc_px(sheight, h)
        clip_id = f"clip-{slot.id}"

        clip_path = ET.SubElement(self._defs, "clipPath", attrib={"id": clip_id})
        ET.SubElement(clip_path, "rect", attrib={
            "x": f"{x:.1f}", "y": f"{y:.1f}", "width": f"{sw:.1f}", "height": f"{sh:.1f}",
        })

        image_url = value if isinstance(value, str) else str(value)
        ET.SubElement(svg, "image", attrib={
            "href": image_url, "x": f"{x:.1f}", "y": f"{y:.1f}",
            "width": f"{sw:.1f}", "height": f"{sh:.1f}",
            "preserveAspectRatio": "xMidYMid slice", "clip-path": f"url(#{clip_id})",
        })

    def _render_button_slot(self, svg: ET.Element, slot: Slot, raw_value: Any, value: Any, w: int, h: int) -> None:
        sx, sy, swidth, sheight = self._effective_geometry(slot, raw_value)
        x, y = self._calc_px(sx, w), self._calc_px(sy, h)
        sw, sh = self._calc_px(swidth, w), self._calc_px(sheight, h)

        if isinstance(value, dict):
            label = value.get("label", value.get("text", ""))
            bg_color = value.get("bg_color") or slot.bg_color or "#333333"
            text_color = value.get("text_color") or slot.text_color or "#ffffff"
        else:
            label = str(value)
            bg_color = slot.bg_color or "#333333"
            text_color = slot.text_color or "#ffffff"

        if not label and slot.default_label:
            label = slot.default_label

        ET.SubElement(svg, "rect", attrib={
            "x": f"{x:.1f}", "y": f"{y:.1f}", "width": f"{sw:.1f}", "height": f"{sh:.1f}",
            "rx": "4", "ry": "4", "fill": bg_color,
        })

        font_size_num = (raw_value.get("font_size") if isinstance(raw_value, dict) else None) or slot.font_size_guideline or "14"
        font_size_num = "".join(c for c in str(font_size_num) if c.isdigit() or c == ".") or "14"

        text_elem = ET.SubElement(svg, "text", attrib={
            "x": f"{x + sw / 2:.1f}", "y": f"{y + sh / 2:.1f}",
            "font-family": _DEFAULT_FONT_FAMILY,
            "font-size": font_size_num, "font-weight": "bold",
            "fill": text_color, "text-anchor": "middle", "dominant-baseline": "central",
            "data-content": "true",
        })
        text_elem.text = label if label else "Button"

    def _render_placeholder(self, svg: ET.Element, slot: Slot, raw_value: Any, w: int, h: int) -> None:
        sx, sy, swidth, sheight = self._effective_geometry(slot, raw_value)
        x, y = self._calc_px(sx, w), self._calc_px(sy, h)
        sw, sh = self._calc_px(swidth, w), self._calc_px(sheight, h)

        ET.SubElement(svg, "rect", attrib={
            "x": f"{x:.1f}", "y": f"{y:.1f}", "width": f"{sw:.1f}", "height": f"{sh:.1f}",
            "fill": "none", "stroke": "#cccccc", "stroke-width": "1", "stroke-dasharray": "5,5",
        })

        # Always use a generic structural label — never slot.description or
        # slot.default_label, which contain template-specific dummy copy.
        # NanoBanana Pro reads the reference image during the i2i pass; showing
        # "Blue Pen Sale!" on a Ramen banner would poison the AI's output.
        _generic = {"text": "Text Here", "button": "Button", "image": "Image", "image_or_text": "Content Here"}
        label = _generic.get(slot.type.value, f"{slot.type.value}")
        text_elem = ET.SubElement(svg, "text", attrib={
            "x": f"{x + sw / 2:.1f}", "y": f"{y + sh / 2:.1f}",
            "font-family": _DEFAULT_FONT_FAMILY,
            "font-size": "12", "fill": "#999999",
            "text-anchor": "middle", "dominant-baseline": "central",
        })
        text_elem.text = label

    @staticmethod
    def _extract_prompt(value: Any) -> str | None:
        """Return the prompt string from a slot value, or None."""
        if isinstance(value, dict):
            prompt = value.get("prompt", "")
            if prompt and str(prompt).strip():
                return str(prompt).strip()
        if hasattr(value, "prompt"):
            prompt = getattr(value, "prompt", "")
            if prompt and str(prompt).strip():
                return str(prompt).strip()
        return None

    @staticmethod
    def _has_image_url(value: Any) -> bool:
        """Return True if the value contains a non-empty image/source URL."""
        if isinstance(value, dict):
            for key in ("source_url", "image_url", "url", "href"):
                url = value.get(key, "")
                if url and str(url).strip():
                    return True
            return False
        for attr in ("source_url", "image_url", "url"):
            if hasattr(value, attr):
                url = getattr(value, attr, "")
                if url and str(url).strip():
                    return True
        return False

    def _render_prompt_placeholder(
        self, svg: ET.Element, slot: Slot, raw_value: Any, prompt: str, w: int, h: int
    ) -> None:
        """Render a purple-tinted placeholder indicating an AI prompt is pending."""
        sx, sy, swidth, sheight = self._effective_geometry(slot, raw_value)
        x, y = self._calc_px(sx, w), self._calc_px(sy, h)
        sw, sh = self._calc_px(swidth, w), self._calc_px(sheight, h)

        # Purple/indigo dashed border rectangle
        ET.SubElement(svg, "rect", attrib={
            "x": f"{x:.1f}", "y": f"{y:.1f}",
            "width": f"{sw:.1f}", "height": f"{sh:.1f}",
            "fill": "#f0ebff", "fill-opacity": "0.5",
            "stroke": "#6c5ce7", "stroke-width": "1.5",
            "stroke-dasharray": "6,4", "rx": "4", "ry": "4",
        })

        # Sparkle / magic icon (small star shape) near the top-left
        icon_size = min(sw, sh, 20)
        icon_x = x + 8
        icon_y = y + 8 + icon_size / 2
        sparkle = ET.SubElement(svg, "text", attrib={
            "x": f"{icon_x:.1f}", "y": f"{icon_y:.1f}",
            "font-family": _DEFAULT_FONT_FAMILY,
            "font-size": f"{icon_size:.0f}",
            "fill": "#6c5ce7",
            "text-anchor": "start", "dominant-baseline": "central",
        })
        sparkle.text = "\u2728"  # sparkles unicode character

        # Truncate prompt to 30 characters
        display_prompt = prompt[:30] + "..." if len(prompt) > 30 else prompt
        label = f"AI: {display_prompt}"

        text_elem = ET.SubElement(svg, "text", attrib={
            "x": f"{x + sw / 2:.1f}", "y": f"{y + sh / 2:.1f}",
            "font-family": _DEFAULT_FONT_FAMILY,
            "font-size": "11", "fill": "#6c5ce7",
            "text-anchor": "middle", "dominant-baseline": "central",
        })
        text_elem.text = label

    @staticmethod
    def _calc_px(percent: float, total: int) -> float:
        return (percent / 100.0) * total
