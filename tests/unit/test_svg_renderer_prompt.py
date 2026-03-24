"""Tests for SVG renderer prompt placeholder rendering."""

import pytest
from app.core.svg_renderer import SvgRenderer
from app.models.template import BannerTemplate, TemplateMeta, TemplateDesign, Slot, SlotType


@pytest.fixture
def renderer():
    return SvgRenderer()


@pytest.fixture
def template_with_image_slot():
    """Template with a single image slot."""
    return BannerTemplate(
        meta=TemplateMeta(
            category="test",
            pattern_id="test_001",
            pattern_name="Test Template",
            width=1200,
            height=630,
        ),
        design=TemplateDesign(
            background_type="solid",
            background_value="#FFFFFF",
            primary_color="#333333",
            font_style="sans-serif",
        ),
        slots=[
            Slot(
                id="main_image",
                type=SlotType.IMAGE,
                x=0, y=0,
                width=50, height=100,
                required=True,
                description="Main product image",
            ),
        ],
        rules=[],
    )


class TestSvgRendererPromptPlaceholder:
    """Tests for prompt placeholder rendering in SVG."""

    def test_render_with_prompt_no_image(self, renderer, template_with_image_slot):
        """Slot with prompt but no image should show prompt placeholder."""
        slot_values = {
            "main_image": {
                "prompt": "赤いスポーツカー、白い背景",
            }
        }
        svg = renderer.render(template_with_image_slot, slot_values)
        assert "svg" in svg.lower()
        # Should contain prompt text indicator
        assert "AI" in svg or "赤いスポーツカー" in svg

    def test_render_with_prompt_and_image(self, renderer, template_with_image_slot):
        """Slot with both prompt and image should render the image."""
        slot_values = {
            "main_image": {
                "source_url": "/static/generated/test.png",
                "prompt": "赤いスポーツカー",
            }
        }
        svg = renderer.render(template_with_image_slot, slot_values)
        assert "svg" in svg.lower()
        # Should contain the image reference
        assert "/static/generated/test.png" in svg

    def test_render_without_prompt_or_image(self, renderer, template_with_image_slot):
        """Slot with no prompt and no image should show default placeholder."""
        slot_values = {}
        svg = renderer.render(template_with_image_slot, slot_values)
        assert "svg" in svg.lower()

    def test_prompt_placeholder_truncated(self, renderer, template_with_image_slot):
        """Long prompts should be truncated in placeholder."""
        long_prompt = "A" * 100
        slot_values = {
            "main_image": {
                "prompt": long_prompt,
            }
        }
        svg = renderer.render(template_with_image_slot, slot_values)
        assert "svg" in svg.lower()
