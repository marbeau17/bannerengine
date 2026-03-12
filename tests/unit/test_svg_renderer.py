"""Unit tests for app.core.svg_renderer.SvgRenderer.

8 tests covering complete template rendering, individual slot types,
placeholder rendering, coordinate conversion, and valid SVG output.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from app.core.svg_renderer import SvgRenderer
from app.models.template import (
    BannerTemplate,
    Slot,
    SlotType,
    TemplateDesign,
    TemplateMeta,
)

SVG_NS = "http://www.w3.org/2000/svg"
XLINK_NS = "http://www.w3.org/1999/xlink"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_template(
    width: int = 1000,
    height: int = 500,
    slots: list[Slot] | None = None,
    bg_type: str = "solid",
    bg_value: str = "#ffffff",
) -> BannerTemplate:
    return BannerTemplate(
        meta=TemplateMeta(
            category="test",
            pattern_id="test_01",
            pattern_name="Test Template",
            width=width,
            height=height,
        ),
        design=TemplateDesign(
            background_type=bg_type,
            background_value=bg_value,
            primary_color="#000000",
            font_style="default",
        ),
        slots=slots or [],
        rules=[],
    )


def _text_slot(slot_id: str = "txt", x: float = 10, y: float = 10, w: float = 30, h: float = 10) -> Slot:
    return Slot(
        id=slot_id, type=SlotType.TEXT,
        x=x, y=y, width=w, height=h,
        required=True, font_size_guideline="20px", font_weight="bold", color="#111111",
    )


def _image_slot(slot_id: str = "img") -> Slot:
    return Slot(
        id=slot_id, type=SlotType.IMAGE,
        x=0, y=0, width=50, height=50,
        required=True,
    )


def _button_slot(slot_id: str = "btn") -> Slot:
    return Slot(
        id=slot_id, type=SlotType.BUTTON,
        x=60, y=80, width=30, height=10,
        required=True,
        default_label="Go",
        bg_color="#333333",
        text_color="#ffffff",
        font_size_guideline="14px",
    )


def _parse_svg(svg_string: str) -> ET.Element:
    """Parse an SVG string into an ElementTree Element."""
    return ET.fromstring(svg_string)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestRenderCompleteTemplate:
    """Render a full template with all slot types populated."""

    def test_render_complete_template(self, svg_renderer: SvgRenderer):
        template = _make_template(
            slots=[_text_slot(), _image_slot(), _button_slot()],
        )
        values = {
            "txt": "Hello World",
            "img": "https://example.com/photo.jpg",
            "btn": {"label": "Click Me", "bg_color": "#ff0000"},
        }
        svg = svg_renderer.render(template, values)

        assert svg  # non-empty string
        root = _parse_svg(svg)
        assert root.tag == f"{{{SVG_NS}}}svg"

        # Check the viewBox matches template dimensions.
        assert root.get("viewBox") == "0 0 1000 500"


class TestRenderTextSlot:
    """Text slot renders a <text> element with the supplied value."""

    def test_render_text_slot(self, svg_renderer: SvgRenderer):
        template = _make_template(slots=[_text_slot()])
        svg = svg_renderer.render(template, {"txt": "Banner Text"})

        root = _parse_svg(svg)
        texts = root.findall(f".//{{{SVG_NS}}}text")
        text_contents = [t.text for t in texts if t.text]
        assert "Banner Text" in text_contents


class TestRenderImageSlot:
    """Image slot renders an <image> element with the supplied URL."""

    def test_render_image_slot(self, svg_renderer: SvgRenderer):
        template = _make_template(slots=[_image_slot()])
        url = "https://example.com/car.jpg"
        svg = svg_renderer.render(template, {"img": url})

        root = _parse_svg(svg)
        images = root.findall(f".//{{{SVG_NS}}}image")
        hrefs = [
            img.get("href") or img.get(f"{{{XLINK_NS}}}href") for img in images
        ]
        assert url in hrefs


class TestRenderButtonSlot:
    """Button slot renders a rect background and text label."""

    def test_render_button_slot(self, svg_renderer: SvgRenderer):
        template = _make_template(slots=[_button_slot()])
        svg = svg_renderer.render(template, {"btn": {"label": "Buy Now"}})

        root = _parse_svg(svg)
        # Expect a rect for the button background
        rects = root.findall(f".//{{{SVG_NS}}}rect")
        assert len(rects) >= 2  # background rect + button rect

        # Expect the label text
        texts = root.findall(f".//{{{SVG_NS}}}text")
        text_contents = [t.text for t in texts if t.text]
        assert "Buy Now" in text_contents


class TestRenderEmptyValues:
    """Empty/None slot values render placeholder elements."""

    def test_render_empty_values(self, svg_renderer: SvgRenderer):
        template = _make_template(slots=[_text_slot()])
        svg = svg_renderer.render(template, {})

        root = _parse_svg(svg)
        # Placeholder renders a dashed-border rect
        rects = root.findall(f".//{{{SVG_NS}}}rect")
        dashed = [r for r in rects if r.get("stroke-dasharray")]
        assert len(dashed) >= 1


class TestPercentageToPixelConversion:
    """_calc_px correctly converts percentage to pixel values."""

    def test_percentage_to_pixel_conversion(self):
        # 25% of 1000px = 250px
        assert SvgRenderer._calc_px(25.0, 1000) == 250.0
        # 0% = 0
        assert SvgRenderer._calc_px(0.0, 800) == 0.0
        # 100% of 600 = 600
        assert SvgRenderer._calc_px(100.0, 600) == 600.0
        # 50% of 500 = 250
        assert SvgRenderer._calc_px(50.0, 500) == 250.0


class TestSvgValidXml:
    """Rendered SVG output is valid XML that can be parsed."""

    def test_svg_valid_xml(self, svg_renderer: SvgRenderer):
        template = _make_template(
            slots=[_text_slot(), _image_slot()],
        )
        values = {"txt": "Valid XML Test", "img": "https://example.com/img.png"}
        svg = svg_renderer.render(template, values)

        # Should not raise any XML parsing errors.
        root = ET.fromstring(svg)
        assert root is not None
        assert root.get("width") == "1000"
        assert root.get("height") == "500"


class TestRenderBackgroundColor:
    """Background color is rendered as the first rect element."""

    def test_render_background_color(self, svg_renderer: SvgRenderer):
        template = _make_template(bg_value="#1a1a2e")
        svg = svg_renderer.render(template, {})

        root = _parse_svg(svg)
        rects = root.findall(f".//{{{SVG_NS}}}rect")
        assert len(rects) >= 1
        bg_rect = rects[0]
        assert bg_rect.get("fill") == "#1a1a2e"
        assert bg_rect.get("width") == "1000"
        assert bg_rect.get("height") == "500"
