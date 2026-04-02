"""Tests for PreviewService - specifically the sync/async template resolution."""

from __future__ import annotations

import pytest

from app.core.svg_renderer import SvgRenderer
from app.models.template import (
    BannerTemplate,
    Slot,
    SlotType,
    TemplateDesign,
    TemplateMeta,
)
from app.services.preview_service import PreviewService
from app.services.template_service import TemplateService
from app.core.exceptions import TemplateNotFoundError


def _make_template() -> BannerTemplate:
    return BannerTemplate(
        meta=TemplateMeta(
            category="test",
            pattern_id="test_01",
            pattern_name="Test Template",
            width=800,
            height=400,
        ),
        design=TemplateDesign(
            background_type="solid",
            background_value="#ffffff",
            primary_color="#000000",
            font_style="default",
        ),
        slots=[
            Slot(
                id="headline",
                type=SlotType.TEXT,
                x=10, y=10, width=80, height=15,
                required=True,
            ),
        ],
        rules=[],
    )


@pytest.fixture
def template_service() -> TemplateService:
    service = TemplateService()
    tmpl = _make_template()
    service._templates[tmpl.meta.pattern_id] = tmpl
    return service


@pytest.fixture
def preview_service(template_service: TemplateService) -> PreviewService:
    return PreviewService(
        renderer=SvgRenderer(),
        template_service=template_service,
    )


class TestPreviewServiceResolveTemplate:
    """PreviewService._resolve_template must call sync get_template (not await it)."""

    @pytest.mark.asyncio
    async def test_generate_preview_returns_svg(self, preview_service: PreviewService):
        """generate_preview should return valid SVG without raising TypeError."""
        svg = await preview_service.generate_preview("test_01", {"headline": "Hello"})
        assert "<svg" in svg
        assert "Hello" in svg

    @pytest.mark.asyncio
    async def test_generate_thumbnail_returns_svg(self, preview_service: PreviewService):
        """generate_thumbnail should work without slot values."""
        svg = await preview_service.generate_thumbnail("test_01")
        assert "<svg" in svg

    @pytest.mark.asyncio
    async def test_resolve_template_not_found(self, preview_service: PreviewService):
        """Should raise TemplateNotFoundError for unknown pattern_id."""
        with pytest.raises(TemplateNotFoundError):
            await preview_service.generate_preview("nonexistent", {})

    @pytest.mark.asyncio
    async def test_preview_with_image_dict_slot(self, preview_service: PreviewService):
        """Preview should handle image slots stored as dicts."""
        # Add an image slot to the template
        tmpl = preview_service._template_service.get_template("test_01")
        tmpl.slots.append(
            Slot(
                id="hero_image", type=SlotType.IMAGE,
                x=0, y=30, width=100, height=70,
                required=False,
            )
        )
        slot_values = {
            "headline": "Test",
            "hero_image": {"source_url": "https://example.com/img.png", "prompt": "", "fit": "cover"},
        }
        svg = await preview_service.generate_preview("test_01", slot_values)
        assert "example.com/img.png" in svg
