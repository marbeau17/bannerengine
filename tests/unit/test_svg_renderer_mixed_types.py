"""Tests for SVG renderer handling mixed slot value types.

Covers the scenario where session stores text slots as strings,
image slots as dicts, and button slots as dicts — the renderer
must handle all combinations without breaking.
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


def _make_template(slots: list[Slot]) -> BannerTemplate:
    return BannerTemplate(
        meta=TemplateMeta(
            category="test", pattern_id="mix_01",
            pattern_name="Mixed Test", width=1200, height=628,
        ),
        design=TemplateDesign(
            background_type="solid", background_value="#ffffff",
            primary_color="#000000", font_style="default",
        ),
        slots=slots,
        rules=[],
    )


@pytest.fixture
def renderer() -> SvgRenderer:
    return SvgRenderer()


class TestMixedSlotValueTypes:
    """Renderer handles the mixed types that the session actually stores."""

    def test_text_as_string_image_as_dict_button_as_dict(self, renderer: SvgRenderer):
        """Realistic session state: text=str, image=dict, button=dict."""
        template = _make_template([
            Slot(id="title", type=SlotType.TEXT, x=10, y=5, width=80, height=10, required=True),
            Slot(id="photo", type=SlotType.IMAGE, x=0, y=20, width=60, height=80, required=True),
            Slot(id="cta", type=SlotType.BUTTON, x=65, y=80, width=30, height=10, required=True,
                 default_label="Buy", bg_color="#333", text_color="#fff"),
        ])
        values = {
            "title": "Sale Today",  # str (as stored by slots router)
            "photo": {"source_url": "https://img.example.com/car.jpg", "prompt": "", "fit": "cover"},
            "cta": {"label": "Shop Now", "bg_color": "#e94560", "text_color": "#ffffff"},
        }
        svg = renderer.render(template, values)
        root = ET.fromstring(svg)

        texts = [t.text for t in root.findall(f".//{{{SVG_NS}}}text") if t.text]
        assert "Sale Today" in texts
        assert "Shop Now" in texts

        images = root.findall(f".//{{{SVG_NS}}}image")
        hrefs = [img.get("href") for img in images]
        assert "https://img.example.com/car.jpg" in hrefs

    def test_image_slot_with_string_value_backward_compat(self, renderer: SvgRenderer):
        """Old-style string URL for image slot should still render."""
        template = _make_template([
            Slot(id="img", type=SlotType.IMAGE, x=0, y=0, width=100, height=100, required=True),
        ])
        svg = renderer.render(template, {"img": "https://example.com/old.jpg"})
        assert "old.jpg" in svg

    def test_image_slot_with_source_url_dict(self, renderer: SvgRenderer):
        """New-style dict with source_url for image slot."""
        template = _make_template([
            Slot(id="img", type=SlotType.IMAGE, x=0, y=0, width=100, height=100, required=True),
        ])
        svg = renderer.render(template, {"img": {"source_url": "https://example.com/new.jpg"}})
        assert "new.jpg" in svg

    def test_image_slot_with_image_url_dict(self, renderer: SvgRenderer):
        """Dict with image_url key (from SlotValue model) for image slot."""
        template = _make_template([
            Slot(id="img", type=SlotType.IMAGE, x=0, y=0, width=100, height=100, required=True),
        ])
        svg = renderer.render(template, {"img": {"image_url": "https://example.com/alt.jpg"}})
        assert "alt.jpg" in svg

    def test_button_slot_with_string_value(self, renderer: SvgRenderer):
        """Button slot receiving a plain string should still render."""
        template = _make_template([
            Slot(id="btn", type=SlotType.BUTTON, x=10, y=80, width=30, height=10,
                 required=True, bg_color="#333", text_color="#fff"),
        ])
        svg = renderer.render(template, {"btn": "Click Me"})
        root = ET.fromstring(svg)
        texts = [t.text for t in root.findall(f".//{{{SVG_NS}}}text") if t.text]
        assert "Click Me" in texts


class TestImageOrTextSlotRendering:
    """image_or_text slot rendering with different value shapes."""

    def test_iot_as_text_string(self, renderer: SvgRenderer):
        """image_or_text slot with plain text string renders as text."""
        template = _make_template([
            Slot(id="logo", type=SlotType.IMAGE_OR_TEXT, x=10, y=10, width=20, height=10, required=True),
        ])
        svg = renderer.render(template, {"logo": "Brand Name"})
        assert "Brand Name" in svg

    def test_iot_as_image_dict(self, renderer: SvgRenderer):
        """image_or_text slot with slot_type=image dict renders as image."""
        template = _make_template([
            Slot(id="logo", type=SlotType.IMAGE_OR_TEXT, x=10, y=10, width=20, height=10, required=True),
        ])
        svg = renderer.render(template, {
            "logo": {"slot_type": "image", "source_url": "https://example.com/logo.png"},
        })
        assert "logo.png" in svg

    def test_iot_as_text_dict(self, renderer: SvgRenderer):
        """image_or_text slot with text dict renders text content."""
        template = _make_template([
            Slot(id="logo", type=SlotType.IMAGE_OR_TEXT, x=10, y=10, width=20, height=10, required=True),
        ])
        svg = renderer.render(template, {"logo": {"text": "My Brand"}})
        assert "My Brand" in svg
