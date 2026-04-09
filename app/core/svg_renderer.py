"""Server-side SVG generation for banner templates."""

from __future__ import annotations

import base64
import mimetypes
import os
import re
import xml.etree.ElementTree as ET
from typing import Any

from app.core.exceptions import GenerationError
from app.models.template import BannerTemplate, Slot, SlotType, TemplateDesign


_DEFAULT_FONT_FAMILY = "Hiragino Kaku Gothic ProN, Hiragino Sans, Yu Gothic, Arial, Apple Color Emoji, sans-serif"


class SvgRenderer:
    """Renders a BannerTemplate with slot values into an SVG string."""

    # ── SVG Filter Presets ─────────────────────────────────────────────────────
    # Each preset is a function that receives (defs_element, filter_id, params)
    # and creates the appropriate <filter> children inside <defs>.

    @staticmethod
    def _add_filter_neon_glow(defs: ET.Element, fid: str, color: str, blur: float) -> str:
        """Outer neon glow: blurred, saturated duplicate behind text."""
        f = ET.SubElement(defs, "filter", attrib={
            "id": fid, "x": "-50%", "y": "-50%", "width": "200%", "height": "200%",
        })
        ET.SubElement(f, "feGaussianBlur", attrib={
            "in": "SourceGraphic", "stdDeviation": f"{blur:.1f}", "result": "blur",
        })
        flood = ET.SubElement(f, "feFlood", attrib={
            "flood-color": color, "flood-opacity": "0.85", "result": "glowColor",
        })
        ET.SubElement(f, "feComposite", attrib={
            "in": "glowColor", "in2": "blur", "operator": "in", "result": "coloredBlur",
        })
        merge = ET.SubElement(f, "feMerge")
        ET.SubElement(merge, "feMergeNode", attrib={"in": "coloredBlur"})
        ET.SubElement(merge, "feMergeNode", attrib={"in": "coloredBlur"})
        ET.SubElement(merge, "feMergeNode", attrib={"in": "SourceGraphic"})
        return fid

    @staticmethod
    def _add_filter_drop_shadow(defs: ET.Element, fid: str, color: str, blur: float,
                                 dx: float = 3, dy: float = 3, opacity: float = 0.7) -> str:
        """Classic drop shadow behind text."""
        f = ET.SubElement(defs, "filter", attrib={
            "id": fid, "x": "-20%", "y": "-20%", "width": "140%", "height": "140%",
        })
        ET.SubElement(f, "feDropShadow", attrib={
            "dx": f"{dx:.1f}", "dy": f"{dy:.1f}",
            "stdDeviation": f"{blur:.1f}",
            "flood-color": color, "flood-opacity": f"{opacity:.2f}",
        })
        return fid

    @staticmethod
    def _add_filter_outline_stroke(defs: ET.Element, fid: str, color: str, width: float) -> str:
        """Thick colored outline around text via morphology dilation."""
        f = ET.SubElement(defs, "filter", attrib={
            "id": fid, "x": "-10%", "y": "-10%", "width": "120%", "height": "120%",
        })
        ET.SubElement(f, "feMorphology", attrib={
            "in": "SourceAlpha", "operator": "dilate",
            "radius": f"{width:.1f}", "result": "expanded",
        })
        flood = ET.SubElement(f, "feFlood", attrib={
            "flood-color": color, "flood-opacity": "1", "result": "strokeColor",
        })
        ET.SubElement(f, "feComposite", attrib={
            "in": "strokeColor", "in2": "expanded", "operator": "in", "result": "stroke",
        })
        merge = ET.SubElement(f, "feMerge")
        ET.SubElement(merge, "feMergeNode", attrib={"in": "stroke"})
        ET.SubElement(merge, "feMergeNode", attrib={"in": "SourceGraphic"})
        return fid

    @staticmethod
    def _add_filter_metallic(defs: ET.Element, fid: str, color: str, blur: float) -> str:
        """Metallic / emboss feel: specular lighting + drop shadow."""
        f = ET.SubElement(defs, "filter", attrib={
            "id": fid, "x": "-20%", "y": "-20%", "width": "140%", "height": "140%",
        })
        ET.SubElement(f, "feGaussianBlur", attrib={
            "in": "SourceAlpha", "stdDeviation": "1", "result": "alphaBlur",
        })
        spec = ET.SubElement(f, "feSpecularLighting", attrib={
            "in": "alphaBlur", "surfaceScale": "5",
            "specularConstant": "0.8", "specularExponent": "20",
            "lighting-color": color, "result": "specOut",
        })
        ET.SubElement(spec, "fePointLight", attrib={
            "x": "-5000", "y": "-10000", "z": "15000",
        })
        ET.SubElement(f, "feComposite", attrib={
            "in": "specOut", "in2": "SourceAlpha", "operator": "in", "result": "specClip",
        })
        merge = ET.SubElement(f, "feMerge")
        ET.SubElement(merge, "feMergeNode", attrib={"in": "SourceGraphic"})
        ET.SubElement(merge, "feMergeNode", attrib={"in": "specClip"})
        return fid

    @staticmethod
    def _add_filter_outline_and_shadow(
        defs: ET.Element, fid: str,
        stroke_color: str, stroke_width: float,
        shadow_color: str, shadow_dx: float, shadow_dy: float,
        shadow_blur: float, shadow_opacity: float,
    ) -> str:
        """Composite: colored outline stroke + cast drop shadow beneath.

        Chain: dilate SourceAlpha → color stroke → merge with source graphic →
               blur that composite → flood shadow color → offset → merge shadow behind.
        """
        f = ET.SubElement(defs, "filter", attrib={
            "id": fid, "x": "-25%", "y": "-25%", "width": "150%", "height": "150%",
        })
        # ── Step 1: Expand alpha → colored outline stroke ──────────────────────
        ET.SubElement(f, "feMorphology", attrib={
            "in": "SourceAlpha", "operator": "dilate",
            "radius": f"{stroke_width:.1f}", "result": "expanded",
        })
        ET.SubElement(f, "feFlood", attrib={
            "flood-color": stroke_color, "flood-opacity": "1", "result": "strokeColor",
        })
        ET.SubElement(f, "feComposite", attrib={
            "in": "strokeColor", "in2": "expanded", "operator": "in", "result": "stroke",
        })
        # ── Step 2: Merge stroke behind source graphic → stroked text ─────────
        merge1 = ET.SubElement(f, "feMerge", attrib={"result": "strokeAndText"})
        ET.SubElement(merge1, "feMergeNode", attrib={"in": "stroke"})
        ET.SubElement(merge1, "feMergeNode", attrib={"in": "SourceGraphic"})
        # ── Step 3: Blur the stroked composite → drop shadow beneath ─────────
        ET.SubElement(f, "feGaussianBlur", attrib={
            "in": "strokeAndText", "stdDeviation": f"{shadow_blur:.1f}", "result": "blur",
        })
        ET.SubElement(f, "feFlood", attrib={
            "flood-color": shadow_color,
            "flood-opacity": f"{shadow_opacity:.2f}",
            "result": "shadowFlood",
        })
        ET.SubElement(f, "feComposite", attrib={
            "in": "shadowFlood", "in2": "blur", "operator": "in", "result": "shadow",
        })
        ET.SubElement(f, "feOffset", attrib={
            "in": "shadow",
            "dx": f"{shadow_dx:.1f}", "dy": f"{shadow_dy:.1f}",
            "result": "offsetShadow",
        })
        # ── Step 4: Final composite — shadow at back, stroked text in front ───
        merge2 = ET.SubElement(f, "feMerge")
        ET.SubElement(merge2, "feMergeNode", attrib={"in": "offsetShadow"})
        ET.SubElement(merge2, "feMergeNode", attrib={"in": "strokeAndText"})
        return fid

    @staticmethod
    def _add_filter_stroke_shadow(
        defs: ET.Element, fid: str,
        shadow_color: str, dx: float, dy: float, blur: float, opacity: float,
    ) -> str:
        """Drop-shadow filter using only feGaussianBlur + feFlood + feComposite + feOffset + feMerge.

        No feMorphology — fully Illustrator-safe. Applied to the stroke (bottom) text
        element of the dual-text outline_and_shadow render path.
        """
        f = ET.SubElement(defs, "filter", attrib={
            "id": fid, "x": "-20%", "y": "-20%", "width": "140%", "height": "140%",
        })
        ET.SubElement(f, "feGaussianBlur", attrib={
            "in": "SourceAlpha", "stdDeviation": f"{blur:.1f}", "result": "blur",
        })
        ET.SubElement(f, "feFlood", attrib={
            "flood-color": shadow_color, "flood-opacity": f"{opacity:.2f}", "result": "shadowColor",
        })
        ET.SubElement(f, "feComposite", attrib={
            "in": "shadowColor", "in2": "blur", "operator": "in", "result": "coloredShadow",
        })
        ET.SubElement(f, "feOffset", attrib={
            "in": "coloredShadow", "dx": f"{dx:.1f}", "dy": f"{dy:.1f}", "result": "offsetShadow",
        })
        merge = ET.SubElement(f, "feMerge")
        ET.SubElement(merge, "feMergeNode", attrib={"in": "offsetShadow"})
        ET.SubElement(merge, "feMergeNode", attrib={"in": "SourceGraphic"})
        return fid

    _FILTER_BUILDERS = {
        "neon_glow": _add_filter_neon_glow,
        "drop_shadow": _add_filter_drop_shadow,
        "metallic": _add_filter_metallic,
        # outline_stroke and outline_and_shadow use dual stacked <text> (no feMorphology)
        # outline_and_shadow legacy filter kept for _build_text_filter fallback only
    }

    def _build_text_filter(self, slot_id: str, text_style: dict) -> str | None:
        """Create a <filter> in <defs> from a text_style dict and return the filter ID.

        Reads the following keys from text_style (all optional with sensible defaults):
          effect_type    — "neon_glow" | "drop_shadow" | "outline_stroke" | "metallic"
                           | "outline_and_shadow"
          effect_color   — hex color for the stroke/glow/effect (default #FFFFFF)
          shadow_blur    — blur radius / stdDeviation for glow/shadow/metallic (default 8)
          shadow_dx      — X offset for drop_shadow / outline_and_shadow (default 3)
          shadow_dy      — Y offset for drop_shadow / outline_and_shadow (default 3)
          shadow_opacity — flood-opacity for drop_shadow / outline_and_shadow, 0.0–1.0
          shadow_color   — shadow flood color for outline_and_shadow (default #000000)
          stroke_width   — dilation radius for outline_stroke / outline_and_shadow (default 2)
        """
        effect = text_style.get("effect_type")
        if not effect:
            return None

        fid = f"fx-{slot_id}"
        color = text_style.get("effect_color", "#FFFFFF")

        def _f(key: str, default: float) -> float:
            try:
                return float(text_style.get(key, default))
            except (ValueError, TypeError):
                return default

        # ── Composite effect: outline + drop shadow (custom multi-param signature) ──
        if effect == "outline_and_shadow":
            stroke_width = _f("stroke_width", 2.0)
            shadow_color = text_style.get("shadow_color", "#000000")
            dx = _f("shadow_dx", 0.0)
            dy = _f("shadow_dy", 1.0)
            s_blur = _f("shadow_blur", 1.0)
            opacity = max(0.0, min(1.0, _f("shadow_opacity", 0.48)))
            self._add_filter_outline_and_shadow(
                self._defs, fid, color, stroke_width, shadow_color, dx, dy, s_blur, opacity,
            )
            return fid

        # ── Simple effects via _FILTER_BUILDERS dispatch ─────────────────────
        builder = self._FILTER_BUILDERS.get(effect)
        if not builder:
            return None

        blur = _f("shadow_blur", 8.0)

        if effect == "neon_glow":
            builder(self._defs, fid, color, blur)
        elif effect == "drop_shadow":
            shadow_color = text_style.get("effect_color", "#000000")
            dx = _f("shadow_dx", 0.0)
            dy = _f("shadow_dy", 1.0)
            ds_blur = _f("shadow_blur", 1.0)
            opacity = max(0.0, min(1.0, _f("shadow_opacity", 0.48)))
            builder(self._defs, fid, shadow_color, ds_blur, dx=dx, dy=dy, opacity=opacity)
        elif effect == "outline_stroke":
            stroke_width = _f("stroke_width", 2.0)
            builder(self._defs, fid, color, stroke_width)
        elif effect == "metallic":
            builder(self._defs, fid, color, blur)

        return fid

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

            # No explicit width/height — keep only viewBox so the SVG scales
            # responsively inside its container on the web preview.
            # Export callers (export_svg) re-inject width/height for Illustrator.
            svg = ET.Element("svg", attrib={
                "xmlns": "http://www.w3.org/2000/svg",
                "xmlns:xlink": "http://www.w3.org/1999/xlink",
                "viewBox": f"0 0 {width} {height}",
            })

            self._defs = ET.SubElement(svg, "defs")

            # Inject Google Fonts for AI-selected font families (Silent Muse pipeline)
            _style = ET.SubElement(self._defs, "style")
            _style.text = (
                "@import url('https://fonts.googleapis.com/css2?"
                "family=Noto+Sans+JP:wght@400;700"
                "&family=M+PLUS+Rounded+1c:wght@400;700"
                "&family=Shippori+Mincho:wght@400;700"
                "&family=Dela+Gothic+One"
                "&display=swap');"
            )

            # Soft-edge radial gradient mask for blended FX layers (smoke, steam,
            # bokeh, etc.) — prevents harsh rectangular clipping at bounding-box edges.
            _fe_grad = ET.SubElement(self._defs, "radialGradient", attrib={"id": "soft-edge-grad"})
            ET.SubElement(_fe_grad, "stop", attrib={"offset": "55%", "stop-color": "white"})
            ET.SubElement(_fe_grad, "stop", attrib={"offset": "100%", "stop-color": "black"})
            _fe_mask = ET.SubElement(self._defs, "mask", attrib={
                "id": "soft-edge-mask",
                "maskContentUnits": "objectBoundingBox",
            })
            ET.SubElement(_fe_mask, "rect", attrib={
                "width": "1", "height": "1",
                "fill": "url(#soft-edge-grad)",
            })

            # --- Unified draw pass (template slots + custom layers) ---
            # Build a single list of (kind, item) pairs, skipping hidden slots.
            # kind = "slot" | "custom"
            all_items: list[tuple[str, Any]] = []
            for slot in template.slots:
                value = slot_values.get(slot.id)
                if isinstance(value, dict) and value.get("_hidden"):
                    continue
                all_items.append(("slot", slot))

            custom_layers = slot_values.get("_custom_layers")
            if custom_layers and isinstance(custom_layers, list):
                for layer in custom_layers:
                    all_items.append(("custom", layer))

            # _order. reversed() here converts to back-to-front drawing order so the
            # background is appended to SVG first (visually behind) and top layer appended last.
            order = slot_values.get("_order")
            
            def _item_id(item: tuple[str, Any]) -> str:
                kind, data = item
                return data.id if kind == "slot" else data.get("id", "")
                
            if order and isinstance(order, list):
                order_map = {sid: i for i, sid in enumerate(reversed(order))}
                
                def _sort_key(item: tuple[str, Any]) -> int:
                    iid = _item_id(item)
                    if iid in order_map:
                        return order_map[iid]
                    # If completely missing from saved order, throw background natively to the absolute bottom.
                    # Throw missing normal elements to the absolute top.
                    if iid == "__background__":
                        return -1
                    return len(order)

                all_items.sort(key=_sort_key)
            else:
                # No saved order at all? Just guarantee background is first!
                all_items.sort(key=lambda item: -1 if _item_id(item) == "__background__" else 0)

            for kind, item in all_items:
                if kind == "slot":
                    value = slot_values.get(item.id)
                    self._render_slot(svg, item, value, template)
                else:
                    self._render_custom_layer(svg, item, width, height)

            raw = ET.tostring(svg, encoding="unicode", xml_declaration=False)
            # ET.tostring XML-escapes & → &amp; inside <style> text, which breaks
            # CSS @import URLs containing &family=... parameters.  Un-escape only
            # within <style> blocks so the rest of the SVG stays valid XML.
            raw = re.sub(
                r"(<style[^>]*>)(.*?)(</style>)",
                lambda m: m.group(1) + m.group(2).replace("&amp;", "&") + m.group(3),
                raw,
                flags=re.DOTALL,
            )
            return raw
        except GenerationError:
            raise
        except Exception as exc:
            raise GenerationError(f"SVG rendering failed: {exc}") from exc

    def _render_background_slot(self, svg: ET.Element, slot: Slot, raw_value: Any, w: int, h: int, template: BannerTemplate) -> None:
        """Render the __background__ slot — either user override or template default design."""
        
        # 1) Try drawing user-specified background layer slot values
        source_url = raw_value.get("source_url", "") if isinstance(raw_value, dict) else ""
        fill_color = raw_value.get("fill_color", "") if isinstance(raw_value, dict) else ""

        if source_url:
            clip_id = f"clip-{slot.id}"
            cp = ET.SubElement(self._defs, "clipPath", attrib={"id": clip_id})
            ET.SubElement(cp, "rect", attrib={"x": "0", "y": "0", "width": str(w), "height": str(h)})
            ET.SubElement(svg, "image", attrib={
                "href": self._resolve_href(source_url),
                "x": "0", "y": "0", "width": str(w), "height": str(h),
                "preserveAspectRatio": "xMidYMid slice",
                "clip-path": f"url(#{clip_id})",
            })
            return
            
        if fill_color:
            ET.SubElement(svg, "rect", attrib={
                "x": "0", "y": "0", "width": str(w), "height": str(h),
                "fill": fill_color,
            })
            return
            
        # 2) Fallback: Render base template design if no user slot overrides exist
        design = template.design
        bg_type = (design.background_type or "").lower()
        bg_value = design.background_value or design.primary_color

        if bg_type == "gradient" and bg_value:
            parts = [p.strip() for p in bg_value.split(",")]
            if len(parts) >= 2:
                grad = ET.SubElement(self._defs, "linearGradient",
                                     attrib={"id": "bg-grad", "x1": "0%", "y1": "0%", "x2": "100%", "y2": "100%"})
                ET.SubElement(grad, "stop", attrib={"offset": "0%", "stop-color": parts[0]})
                ET.SubElement(grad, "stop", attrib={"offset": "100%", "stop-color": parts[1]})
                ET.SubElement(svg, "rect", attrib={"x": "0", "y": "0", "width": str(w), "height": str(h), "fill": "url(#bg-grad)"})
            else:
                ET.SubElement(svg, "rect", attrib={"x": "0", "y": "0", "width": str(w), "height": str(h), "fill": parts[0]})
        elif bg_type == "image" and bg_value:
            ET.SubElement(svg, "image", attrib={
                "href": self._resolve_href(bg_value), "x": "0", "y": "0",
                "width": str(w), "height": str(h), "preserveAspectRatio": "xMidYMid slice",
            })
        else:
            fill = bg_value if bg_value else "#ffffff"
            ET.SubElement(svg, "rect", attrib={"x": "0", "y": "0", "width": str(w), "height": str(h), "fill": fill})

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

        # Apply rotation transform around the slot's pixel center
        if isinstance(value, dict):
            _rot_raw = value.get("rotation")
            if _rot_raw is not None:
                try:
                    _rot = float(_rot_raw)
                    if _rot != 0.0:
                        _cx = (x_pct + w_pct / 2.0) / 100.0 * w
                        _cy = (y_pct + h_pct / 2.0) / 100.0 * h
                        slot_group.set("transform", f"rotate({_rot:.2f} {_cx:.1f} {_cy:.1f})")
                        slot_group.set("data-rotation", f"{_rot:.2f}")
                except (TypeError, ValueError):
                    pass

        # BACKGROUND slot: render (or skip) immediately — never show a placeholder
        if slot.type == SlotType.BACKGROUND:
            self._render_background_slot(slot_group, slot, value, w, h, template)
            return

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
            # BACKGROUND slot: always pass through to _render_background_slot
            if slot.type == SlotType.BACKGROUND:
                return value
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

    @staticmethod
    def _append_multiline_text(text_elem: ET.Element, value: str, x_px: float, font_size_px: float) -> None:
        """Split text by newline and create <tspan> elements for multi-line rendering."""
        lines = value.split("\n")
        if len(lines) <= 1:
            text_elem.text = value
            return

        line_height = font_size_px * 1.2
        total_height = line_height * (len(lines) - 1)
        start_dy = -total_height / 2

        for i, line in enumerate(lines):
            tspan_attribs = {"x": f"{x_px:.1f}"}
            if i == 0:
                tspan_attribs["dy"] = f"{start_dy:.1f}"
            else:
                tspan_attribs["dy"] = f"{line_height:.1f}"
            tspan = ET.SubElement(text_elem, "tspan", attrib=tspan_attribs)
            tspan.text = line

    def _render_text_slot(self, svg: ET.Element, slot: Slot, raw_value: Any, value: str, w: int, h: int) -> None:
        sx, sy, swidth, sheight = self._effective_geometry(slot, raw_value)
        x, y = self._calc_px(sx, w), self._calc_px(sy, h)
        sw, sh = self._calc_px(swidth, w), self._calc_px(sheight, h)

        font_size_num, font_weight, color = self._extract_font_props(slot, raw_value)

        # Apply AI text_style overrides (lowest priority — user manual wins last)
        text_style = raw_value.get("text_style") if isinstance(raw_value, dict) else None
        effect_type = (text_style.get("effect_type") if text_style and isinstance(text_style, dict) else None)
        if text_style and isinstance(text_style, dict):
            if text_style.get("font_fill"):
                color = text_style["font_fill"]
            if text_style.get("font_size"):
                font_size_num = str(text_style["font_size"])
            if text_style.get("font_weight"):
                font_weight = str(text_style["font_weight"])

        # User manual overrides always win
        if isinstance(raw_value, dict):
            if raw_value.get("color"):
                color = raw_value["color"]
            if raw_value.get("fill"):
                color = raw_value["fill"]

        # Silent Muse typography overrides
        is_vertical = bool(raw_value.get("vertical", False)) if isinstance(raw_value, dict) else False
        font_family_override = (raw_value.get("font_family") if isinstance(raw_value, dict) else None)
        resolved_font = f"{font_family_override}, {_DEFAULT_FONT_FAMILY}" if font_family_override else _DEFAULT_FONT_FAMILY

        cx_px = x + sw / 2
        try:
            fs_float = float("".join(c for c in str(font_size_num) if c.isdigit() or c == "."))
        except ValueError:
            fs_float = 24.0

        # Shared base attribs (position / font / layout)
        def _base_attribs() -> dict[str, str]:
            if is_vertical:
                return {
                    "x": f"{cx_px:.1f}", "y": f"{y:.1f}",
                    "font-family": resolved_font,
                    "font-size": font_size_num, "font-weight": font_weight,
                    "writing-mode": "vertical-rl", "text-orientation": "upright",
                    "text-anchor": "start", "dominant-baseline": "auto",
                }
            return {
                "x": f"{cx_px:.1f}", "y": f"{y + sh / 2:.1f}",
                "font-family": resolved_font,
                "font-size": font_size_num, "font-weight": font_weight,
                "text-anchor": "middle", "dominant-baseline": "central",
            }

        # ── DUAL-TEXT PATH: outline effects (Illustrator-safe, no feMorphology) ─────
        if effect_type in ("outline_stroke", "outline_and_shadow"):
            assert text_style is not None  # effect_type implies text_style exists
            effect_color = text_style.get("effect_color", "#ffffff")
            # Guard: outline must contrast with fill — if they match, flip to opposite
            if effect_color.lower() == color.lower():
                # Invert: dark fill → white outline, light fill → black outline
                try:
                    _r, _g, _b = int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)
                    effect_color = "#000000" if (_r * 0.299 + _g * 0.587 + _b * 0.114) > 128 else "#ffffff"
                except (ValueError, IndexError):
                    effect_color = "#ffffff" if color.lower() in ("#000000", "#000", "black") else "#000000"
            stroke_width = float(text_style.get("stroke_width", 2))

            # Bottom element: stroke-only (doubled width so N px visible outside fill)
            stroke_attribs: dict[str, str] = {
                **_base_attribs(),
                "stroke": effect_color,
                "stroke-width": f"{stroke_width * 2:.1f}",
                "stroke-linejoin": "round",
                "stroke-linecap": "round",
                "fill": "none",
            }

            if effect_type == "outline_and_shadow":
                _sfid = f"shdw-{slot.id}"
                self._add_filter_stroke_shadow(
                    self._defs, _sfid,
                    shadow_color=text_style.get("shadow_color", "#000000"),
                    dx=float(text_style.get("shadow_dx", 0)),
                    dy=float(text_style.get("shadow_dy", 1)),
                    blur=float(text_style.get("shadow_blur", 1)),
                    opacity=float(text_style.get("shadow_opacity", 0.48)),
                )
                stroke_attribs["filter"] = f"url(#{_sfid})"

            # Top element: fill-only (no stroke), carries data-content marker
            fill_attribs: dict[str, str] = {
                **_base_attribs(),
                "fill": color,
                "data-content": "true",
            }

            stroke_elem = ET.SubElement(svg, "text", attrib=stroke_attribs)
            self._append_multiline_text(stroke_elem, str(value), cx_px, fs_float)
            fill_elem = ET.SubElement(svg, "text", attrib=fill_attribs)
            self._append_multiline_text(fill_elem, str(value), cx_px, fs_float)
            return

        # ── SINGLE-TEXT PATH: neon_glow, drop_shadow, metallic (filter-based) ───────
        filter_id = None
        if text_style and isinstance(text_style, dict) and effect_type:
            filter_id = self._build_text_filter(slot.id, text_style)

        attribs: dict[str, str] = {
            **_base_attribs(),
            "fill": color,
            "data-content": "true",
        }
        if filter_id:
            attribs["filter"] = f"url(#{filter_id})"

        text_elem = ET.SubElement(svg, "text", attrib=attribs)
        self._append_multiline_text(text_elem, str(value), cx_px, fs_float)

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

        # Always-on Drop Shadow for CTA Button (Applies to the entire button group)
        btn_filter_id = self._build_text_filter(slot.id + "-btn-float", {
            "effect_type": "drop_shadow",
            "shadow_color": "#000000",
            "shadow_dx": 0,
            "shadow_dy": 2,
            "shadow_blur": 4,
            "shadow_opacity": 0.35
        })
        svg.set("filter", f"url(#{btn_filter_id})")

        # If AI rasterized a background graphic, use that. Otherwise use flat rect.
        bg_image_url = value.get("bg_image_url") if isinstance(value, dict) else None
        if bg_image_url:
            clip_id = f"clip-{slot.id}-btn"
            clip_path = ET.SubElement(self._defs, "clipPath", attrib={"id": clip_id})
            ET.SubElement(clip_path, "rect", attrib={
                "x": f"{x:.1f}", "y": f"{y:.1f}", "width": f"{sw:.1f}", "height": f"{sh:.1f}",
                "rx": "4", "ry": "4"
            })
            ET.SubElement(svg, "image", attrib={
                "href": self._resolve_href(bg_image_url),
                "x": f"{x:.1f}", "y": f"{y:.1f}",
                "width": f"{sw:.1f}", "height": f"{sh:.1f}",
                "preserveAspectRatio": "xMidYMid slice",
                "clip-path": f"url(#{clip_id})",
            })
        else:
            ET.SubElement(svg, "rect", attrib={
                "x": f"{x:.1f}", "y": f"{y:.1f}", "width": f"{sw:.1f}", "height": f"{sh:.1f}",
                "rx": "4", "ry": "4", "fill": bg_color,
            })

        font_size_num = (raw_value.get("font_size") if isinstance(raw_value, dict) else None) or slot.font_size_guideline or "14"
        font_size_num = "".join(c for c in str(font_size_num) if c.isdigit() or c == ".") or "14"

        cx_px = x + sw / 2
        text_elem = ET.SubElement(svg, "text", attrib={
            "x": f"{cx_px:.1f}", "y": f"{y + sh / 2:.1f}",
            "font-family": _DEFAULT_FONT_FAMILY,
            "font-size": font_size_num, "font-weight": "bold",
            "fill": text_color, "text-anchor": "middle", "dominant-baseline": "central",
            "data-content": "true",
        })
        
        try:
            fs_float = float(font_size_num)
        except ValueError:
            fs_float = 14.0
            
        self._append_multiline_text(text_elem, label if label else "Button", cx_px, fs_float)



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

        blend_mode = layer.get("blend_mode", "normal") or "normal"
        style_parts = []
        blend_filter_id: str | None = None
        if blend_mode and blend_mode != "normal":
            style_parts.append(f"mix-blend-mode:{blend_mode}")
            # Also inject a native SVG feBlend filter for offline SVG renderers
            # (Illustrator, Inkscape) that ignore CSS mix-blend-mode
            blend_filter_id = f"blend_{layer_id}"
            _bf = ET.SubElement(self._defs, "filter", attrib={
                "id": blend_filter_id,
                "x": "0%", "y": "0%", "width": "100%", "height": "100%",
            })
            ET.SubElement(_bf, "feBlend", attrib={
                "in": "SourceGraphic",
                "in2": "BackgroundImage",
                "mode": blend_mode,
            })

        g_attribs: dict[str, str] = {
            "id": layer_id,
            "class": "draggable-slot custom-layer",
            "data-slot-id": layer_id,
            "data-slot-type": layer_type,
            "data-x": f"{float(layer.get('x', 10)):.4f}",
            "data-y": f"{float(layer.get('y', 10)):.4f}",
            "data-w": f"{float(layer.get('width', 30)):.4f}",
            "data-h": f"{float(layer.get('height', 20)):.4f}",
            "opacity": f"{opacity:.2f}",
        }
        if style_parts:
            g_attribs["style"] = ";".join(style_parts)
        if blend_filter_id:
            g_attribs["filter"] = f"url(#{blend_filter_id})"

        # Rotation transform around the layer's pixel center
        _rot_raw = layer.get("rotation")
        if _rot_raw is not None:
            try:
                _rot = float(_rot_raw)
                if _rot != 0.0:
                    _cx = x + lw / 2.0
                    _cy = y + lh / 2.0
                    g_attribs["transform"] = f"rotate({_rot:.2f} {_cx:.1f} {_cy:.1f})"
                    g_attribs["data-rotation"] = f"{_rot:.2f}"
            except (TypeError, ValueError):
                pass

        # Apply soft-edge feather mask to blended image layers (smoke, steam,
        # bokeh, etc.) so volumetric FX fade smoothly at bounding-box edges.
        if layer_type == "image" and blend_mode and blend_mode != "normal":
            g_attribs["mask"] = "url(#soft-edge-mask)"

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
            font_weight = layer.get("font_weight", "normal") or "normal"
            font_family_override = layer.get("font_family")
            resolved_font = f"{font_family_override}, {_DEFAULT_FONT_FAMILY}" if font_family_override else _DEFAULT_FONT_FAMILY
            cx_px = x + lw / 2
            text_el = ET.SubElement(g, "text", attrib={
                "x": f"{cx_px:.1f}", "y": f"{y + lh / 2:.1f}",
                "font-family": resolved_font,
                "font-size": font_size_num,
                "font-weight": font_weight,
                "fill": color,
                "text-anchor": "middle",
                "dominant-baseline": "central",
                "data-content": "true",
            })
            
            try:
                fs_float = float(font_size_num)
            except ValueError:
                fs_float = 24.0
                
            self._append_multiline_text(text_el, str(layer.get("text", "Text Layer")), cx_px, fs_float)
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
                # Empty placeholder — dashed outline + centred label for click/drag target
                ET.SubElement(g, "rect", attrib={
                    "x": f"{x:.1f}", "y": f"{y:.1f}",
                    "width": f"{lw:.1f}", "height": f"{lh:.1f}",
                    "fill": "none", "stroke": "#cccccc",
                    "stroke-width": "1", "stroke-dasharray": "5,5",
                })
                placeholder = ET.SubElement(g, "text", attrib={
                    "x": f"{x + lw / 2:.1f}", "y": f"{y + lh / 2:.1f}",
                    "font-family": _DEFAULT_FONT_FAMILY,
                    "font-size": "14",
                    "fill": "#aaaaaa",
                    "text-anchor": "middle",
                    "dominant-baseline": "central",
                })
                placeholder.text = "Image"

    def _resolve_href(self, url: str) -> str:
        """Return a Base64 data URI for local assets when embed_images is True.

        Converts ``/static/generated/foo.png`` → ``data:image/png;base64,…``.
        Falls back to the original URL for remote addresses or missing files.
        """
        if not self._embed_images:
            return url
        if not url or url.startswith("data:"):
            return url
        # Fetch remote URLs and embed as Base64 so offline tools like Illustrator can render them
        if url.startswith("http://") or url.startswith("https://"):
            import urllib.request
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "BannerEngine/1.0"})
                with urllib.request.urlopen(req, timeout=5.0) as response:
                    img_data = response.read()
                    mime = response.headers.get_content_type() or "image/png"
                    encoded = base64.b64encode(img_data).decode("ascii")
                    return f"data:{mime};base64,{encoded}"
            except Exception:
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
