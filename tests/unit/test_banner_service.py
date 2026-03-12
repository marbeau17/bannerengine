"""Unit tests for app.services.banner_service.BannerService.

Test IDs follow the spec convention UT-RND-001 through UT-RND-008.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.models.banner import RenderInstruction
from app.models.template import (
    BannerTemplate,
    Slot,
    SlotType,
    TemplateDesign,
    TemplateMeta,
)
from app.services.banner_service import BannerService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_template(slots: list[Slot] | None = None) -> BannerTemplate:
    return BannerTemplate(
        meta=TemplateMeta(
            category="used_car",
            pattern_id="car_01",
            pattern_name="Test Car Banner",
            width=1200,
            height=628,
        ),
        design=TemplateDesign(
            background_type="solid",
            background_value="#1a1a2e",
            primary_color="#e94560",
            font_style="modern",
        ),
        slots=slots or [],
        rules=[],
    )


def _text_slot(slot_id: str = "headline", required: bool = True) -> Slot:
    return Slot(
        id=slot_id, type=SlotType.TEXT,
        x=62, y=10, width=35, height=15,
        required=required,
        font_size_guideline="32px", font_weight="bold", color="#ffffff",
    )


def _image_slot(slot_id: str = "hero_image", required: bool = True) -> Slot:
    return Slot(
        id=slot_id, type=SlotType.IMAGE,
        x=0, y=0, width=60, height=100,
        required=required,
    )


def _button_slot(slot_id: str = "cta_button") -> Slot:
    return Slot(
        id=slot_id, type=SlotType.BUTTON,
        x=62, y=85, width=35, height=10,
        required=True,
        default_label="View Details",
        bg_color="#e94560", text_color="#ffffff",
        font_size_guideline="16px",
    )


def _iot_slot(slot_id: str = "logo", required: bool = False) -> Slot:
    return Slot(
        id=slot_id, type=SlotType.IMAGE_OR_TEXT,
        x=62, y=70, width=15, height=10,
        required=required,
    )


def _build_service(template: BannerTemplate) -> BannerService:
    ts = MagicMock()
    ts.get_template.return_value = template
    nbc = MagicMock()
    return BannerService(template_service=ts, nano_banana_client=nbc)


# ---------------------------------------------------------------------------
# UT-RND-001
# ---------------------------------------------------------------------------

class TestFullRenderInstruction:
    """UT-RND-001: create_render_instruction returns a complete RenderInstruction."""

    def test_full_render_instruction(self):
        template = _make_template(
            slots=[_text_slot(), _image_slot(), _button_slot()]
        )
        service = _build_service(template)
        slot_values = {
            "headline": {"content": "Big Sale"},
            "hero_image": {"source_url": "https://example.com/car.jpg"},
            "cta_button": {"content": "Shop Now"},
        }

        result = service.create_render_instruction("car_01", slot_values)

        assert isinstance(result, RenderInstruction)
        assert result.schema_version == "1.0"
        assert result.canvas["width"] == 1200
        assert result.canvas["height"] == 628
        assert len(result.layers) > 0


# ---------------------------------------------------------------------------
# UT-RND-002
# ---------------------------------------------------------------------------

class TestTextSlotInInstruction:
    """UT-RND-002: Text slot produces a text layer."""

    def test_text_slot_in_instruction(self):
        template = _make_template(slots=[_text_slot()])
        service = _build_service(template)
        slot_values = {"headline": {"content": "Hello"}}

        result = service.create_render_instruction("car_01", slot_values)

        text_layers = [l for l in result.layers if l["type"] == "text"]
        assert len(text_layers) == 1
        assert text_layers[0]["content"] == "Hello"
        assert text_layers[0]["layer_id"] == "text_headline"


# ---------------------------------------------------------------------------
# UT-RND-003
# ---------------------------------------------------------------------------

class TestImageSlotInInstruction:
    """UT-RND-003: Image slot produces an image layer."""

    def test_image_slot_in_instruction(self):
        template = _make_template(slots=[_image_slot()])
        service = _build_service(template)
        slot_values = {"hero_image": {"source_url": "https://example.com/car.jpg"}}

        result = service.create_render_instruction("car_01", slot_values)

        image_layers = [l for l in result.layers if l["type"] == "image"]
        assert len(image_layers) == 1
        assert image_layers[0]["source_url"] == "https://example.com/car.jpg"
        assert image_layers[0]["layer_id"] == "image_hero_image"


# ---------------------------------------------------------------------------
# UT-RND-004
# ---------------------------------------------------------------------------

class TestButtonSlotInInstruction:
    """UT-RND-004: Button slot produces rect + text layers."""

    def test_button_slot_in_instruction(self):
        template = _make_template(slots=[_button_slot()])
        service = _build_service(template)
        slot_values = {"cta_button": {"content": "Buy Now"}}

        result = service.create_render_instruction("car_01", slot_values)

        rect_layers = [l for l in result.layers if l["type"] == "rect"]
        text_layers = [l for l in result.layers if l["type"] == "text"]
        assert len(rect_layers) == 1
        assert len(text_layers) == 1
        assert rect_layers[0]["layer_id"] == "button_bg_cta_button"
        assert text_layers[0]["layer_id"] == "button_text_cta_button"
        assert text_layers[0]["content"] == "Buy Now"


# ---------------------------------------------------------------------------
# UT-RND-005
# ---------------------------------------------------------------------------

class TestImageOrTextImagePriority:
    """UT-RND-005: image_or_text with source_url yields image layer."""

    def test_image_or_text_image_priority(self):
        template = _make_template(slots=[_iot_slot(required=True)])
        service = _build_service(template)
        slot_values = {"logo": {"source_url": "https://example.com/logo.png"}}

        result = service.create_render_instruction("car_01", slot_values)

        image_layers = [l for l in result.layers if l["type"] == "image"]
        assert len(image_layers) == 1
        assert image_layers[0]["source_url"] == "https://example.com/logo.png"

    def test_image_or_text_text_fallback(self):
        template = _make_template(slots=[_iot_slot(required=True)])
        service = _build_service(template)
        slot_values = {"logo": {"content": "Brand Name"}}

        result = service.create_render_instruction("car_01", slot_values)

        text_layers = [l for l in result.layers if l["type"] == "text"]
        assert len(text_layers) == 1
        assert text_layers[0]["content"] == "Brand Name"


# ---------------------------------------------------------------------------
# UT-RND-006
# ---------------------------------------------------------------------------

class TestOptionalSlotSkipped:
    """UT-RND-006: Optional slot with no value is skipped entirely."""

    def test_optional_slot_skipped(self):
        template = _make_template(
            slots=[_text_slot(), _iot_slot(required=False)]
        )
        service = _build_service(template)
        slot_values = {"headline": {"content": "Sale"}}  # no 'logo' value

        result = service.create_render_instruction("car_01", slot_values)

        layer_ids = [l["layer_id"] for l in result.layers]
        assert not any("logo" in lid for lid in layer_ids)


# ---------------------------------------------------------------------------
# UT-RND-007
# ---------------------------------------------------------------------------

class TestOutputSchema:
    """UT-RND-007: RenderInstruction has the expected top-level keys."""

    def test_output_schema(self):
        template = _make_template(slots=[_text_slot()])
        service = _build_service(template)
        slot_values = {"headline": {"content": "Test"}}

        result = service.create_render_instruction("car_01", slot_values)

        data = result.model_dump()
        assert "schema_version" in data
        assert "canvas" in data
        assert "layers" in data
        assert "width" in data["canvas"]
        assert "height" in data["canvas"]
        assert "format" in data["canvas"]
        assert "quality" in data["canvas"]
        assert "dpi" in data["canvas"]


# ---------------------------------------------------------------------------
# UT-RND-008
# ---------------------------------------------------------------------------

class TestCoordinateTypes:
    """UT-RND-008: Layer positions and sizes are integer pixels."""

    def test_coordinate_types(self):
        template = _make_template(slots=[_text_slot()])
        service = _build_service(template)
        slot_values = {"headline": {"content": "Coords"}}

        result = service.create_render_instruction("car_01", slot_values)

        for layer in result.layers:
            pos = layer["position"]
            size = layer["size"]
            assert isinstance(pos["x"], int), f"position.x should be int, got {type(pos['x'])}"
            assert isinstance(pos["y"], int), f"position.y should be int, got {type(pos['y'])}"
            assert isinstance(size["width"], int), f"size.width should be int, got {type(size['width'])}"
            assert isinstance(size["height"], int), f"size.height should be int, got {type(size['height'])}"
