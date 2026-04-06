"""Server-side SVG generation for banner templates."""

from __future__ import annotations

import base64
import mimetypes
import os
import xml.etree.ElementTree as ET
from typing import Any

from app.core.exceptions import GenerationError
from app.models.template import BannerTemplate, Slot, SlotType, TemplateDesign


_DEFAULT_FONT_FAMILY = "Hiragino Kaku Gothic ProN, Hiragino Sans, Yu Gothic, Arial, Apple Color Emoji, sans-serif"


class SvgRenderer:
    """Renders a BannerTemplate with slot values into an SVG string."""

    def render(
        self,
        template: BannerTemplate,
        slot_values: dict[str, Any],
        embed_images: bool = False,
    ) -> str:
        """Generate a complete SVG string for the given template and values.

        Args:
            embed_images: When True, resolve local ``/static/…`` image URLs to
                Base64 ``data:`` URIs so the SVG is fully self-contained and
                opens correctly in offline tools like Adobe Illustrator.
                Defaults to False to keep the live web preview lightweight.

        Respects three session keys that extend / reorder the base template:
        - ``_order``         — list of slot IDs controlling draw order (z-index)
        - ``_custom_layers`` — list of freeform layer dicts (rect/circle/text/image)
        """
        self._embed_images = embed_images
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

            # Apply custom draw order (Photoshop convention).
            # _order is stored as draw sequence: index 0 = bottom layer, last index = top layer.
            # We iterate reversed(order) so the bottom layer is drawn first (lowest z-index)
            # and the top layer is drawn last (highest z-index / front of canvas).
            slots = list(template.slots)
            order = slot_values.get("_order")
            if order and isinstance(order, list):
                order_map = {sid: i for i, sid in enumerate(reversed(order))}
                slots.sort(key=lambda s: order_map.get(s.id, len(order)))

            for slot in slots:
                value = slot_values.get(slot.id)
                self._render_slot(svg, slot, value, template)

            # Render freeform custom layers on top (Phase 2)
            custom_layers = slot_values.get("_custom_layers")
            if custom_layers and isinstance(custom_layers, list):
                for layer in custom_layers:
                    self._render_custom_layer(svg, layer, width, height)

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
                "href": self._resolve_href(bg_value), "x": "0", "y": "0",
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
        slot_attribs: dict[str, str] = {
            "id": slot.id,
            "data-name": slot.id,
            "class": "draggable-slot",
            "data-slot-id": slot.id,
            "data-slot-type": slot.type.value,
            "data-x": f"{x_pct:.4f}",
            "data-y": f"{y_pct:.4f}",
            "data-w": f"{w_pct:.4f}",
            "data-h": f"{h_pct:.4f}",
        }
        # Phase 2: apply per-slot opacity if set
        if isinstance(value, dict):
            opacity_raw = value.get("opacity")
            if opacity_raw is not None:
                try:
                    opacity_val = max(0.0, min(1.0, float(opacity_raw)))
                    slot_attribs["opacity"] = f"{opacity_val:.2f}"
                except (ValueError, TypeError):
                    pass
        slot_group = ET.SubElement(svg, "g", attrib=slot_attribs)
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

        image_url = self._resolve_href(value if isinstance(value, str) else str(value))
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

    def _render_custom_layer(self, svg: ET.Element, layer: dict, w: int, h: int) -> None:
        """Render a freeform custom layer (rect / circle / text / image). Phase 2."""
        layer_id = layer.get("id", "custom_unknown")
        layer_type = layer.get("type", "rect")
        x = self._calc_px(float(layer.get("x", 10)), w)
        y = self._calc_px(float(layer.get("y", 10)), h)
        lw = self._calc_px(float(layer.get("width", 30)), w)
        lh = self._calc_px(float(layer.get("height", 20)), h)

        opacity_raw = layer.get("opacity", 1.0)
        try:
            opacity = max(0.0, min(1.0, float(opacity_raw)))
        except (ValueError, TypeError):
            opacity = 1.0

        g_attribs: dict[str, str] = {
            "id": layer_id,
            "class": "draggable-slot custom-layer",
            "data-slot-id": layer_id,
            "data-slot-type": layer_type,
            "data-x": f"{layer.get('x', 10):.4f}",
            "data-y": f"{layer.get('y', 10):.4f}",
            "data-w": f"{layer.get('width', 30):.4f}",
            "data-h": f"{layer.get('height', 20):.4f}",
            "opacity": f"{opacity:.2f}",
        }
        g = ET.SubElement(svg, "g", attrib=g_attribs)

        if layer_type == "rect":
            fill = layer.get("fill", "#4f46e5")
            ET.SubElement(g, "rect", attrib={
                "x": f"{x:.1f}", "y": f"{y:.1f}",
                "width": f"{lw:.1f}", "height": f"{lh:.1f}",
                "fill": fill,
            })
        elif layer_type == "circle":
            fill = layer.get("fill", "#059669")
            cx = x + lw / 2
            cy = y + lh / 2
            r = min(lw, lh) / 2
            ET.SubElement(g, "circle", attrib={
                "cx": f"{cx:.1f}", "cy": f"{cy:.1f}", "r": f"{r:.1f}",
                "fill": fill,
            })
        elif layer_type == "text":
            color = layer.get("color", "#111111")
            font_size = layer.get("font_size", "24")
            font_size_num = "".join(c for c in str(font_size) if c.isdigit() or c == ".") or "24"
            text_el = ET.SubElement(g, "text", attrib={
                "x": f"{x + lw / 2:.1f}", "y": f"{y + lh / 2:.1f}",
                "font-family": _DEFAULT_FONT_FAMILY,
                "font-size": font_size_num,
                "fill": color,
                "text-anchor": "middle",
                "dominant-baseline": "central",
                "data-content": "true",
            })
            text_el.text = str(layer.get("text", "Text Layer"))
        elif layer_type == "image":
            source_url = layer.get("source_url", "")
            if source_url:
                clip_id = f"clip-{layer_id}"
                clip_path = ET.SubElement(self._defs, "clipPath", attrib={"id": clip_id})
                ET.SubElement(clip_path, "rect", attrib={
                    "x": f"{x:.1f}", "y": f"{y:.1f}",
                    "width": f"{lw:.1f}", "height": f"{lh:.1f}",
                })
                ET.SubElement(g, "image", attrib={
                    "href": self._resolve_href(source_url),
                    "x": f"{x:.1f}", "y": f"{y:.1f}",
                    "width": f"{lw:.1f}", "height": f"{lh:.1f}",
                    "preserveAspectRatio": "xMidYMid slice",
                    "clip-path": f"url(#{clip_id})",
                })
            else:
                ET.SubElement(g, "rect", attrib={
                    "x": f"{x:.1f}", "y": f"{y:.1f}",
                    "width": f"{lw:.1f}", "height": f"{lh:.1f}",
                    "fill": "none", "stroke": "#cccccc",
                    "stroke-width": "1", "stroke-dasharray": "5,5",
                })

    def _resolve_href(self, url: str) -> str:
        """Return a Base64 data URI for local assets when embed_images is True.

        Converts ``/static/generated/foo.png`` → ``data:image/png;base64,…``.
        Falls back to the original URL for remote addresses or missing files.
        """
        if not self._embed_images:
            return url
        if not url or url.startswith("data:"):
            return url
        # Resolve server-relative paths to filesystem paths
        local_path = url.lstrip("/") if url.startswith("/") else url
        if not os.path.exists(local_path):
            return url
        mime, _ = mimetypes.guess_type(local_path)
        mime = mime or "image/png"
        with open(local_path, "rb") as f:
            encoded = base64.b64encode(f.read()).decode("ascii")
        return f"data:{mime};base64,{encoded}"

    @staticmethod
    def _calc_px(percent: float, total: int) -> float:
        return (percent / 100.0) * total
