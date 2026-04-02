"""Regression tests for Starlette TemplateResponse API compatibility.

Ensures all HTML-rendering endpoints return 200 with text/html content
after the migration from the old TemplateResponse(name, context) to the
new TemplateResponse(request, name, context) signature.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core.svg_renderer import SvgRenderer
from app.models.template import (
    BannerTemplate,
    Slot,
    SlotType,
    TemplateDesign,
    TemplateMeta,
)
from app.services.template_service import TemplateService

pytestmark = pytest.mark.asyncio


def _sample_template() -> BannerTemplate:
    return BannerTemplate(
        meta=TemplateMeta(
            category="used_car", pattern_id="car_01",
            pattern_name="Test Car", width=1200, height=628,
            aspect_ratio="1.91:1", layout_type="hero_image",
            recommended_use="Testing",
        ),
        design=TemplateDesign(
            background_type="solid", background_value="#1a1a2e",
            primary_color="#e94560", font_style="modern",
        ),
        slots=[
            Slot(id="headline", type=SlotType.TEXT,
                 x=10, y=10, width=80, height=15,
                 required=True, max_chars=30),
            Slot(id="hero_image", type=SlotType.IMAGE,
                 x=0, y=0, width=100, height=100,
                 required=True),
            Slot(id="cta_button", type=SlotType.BUTTON,
                 x=60, y=85, width=30, height=10,
                 required=True, default_label="View Details",
                 bg_color="#e94560", text_color="#ffffff"),
        ],
        rules=[],
    )


@pytest_asyncio.fixture
async def client():
    from app.main import app
    service = TemplateService()
    tmpl = _sample_template()
    service._templates[tmpl.meta.pattern_id] = tmpl
    app.state.template_service = service
    app.state.svg_renderer = SvgRenderer()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


class TestTemplateResponseCompat:
    """All endpoints using TemplateResponse render correctly."""

    async def test_list_templates_html(self, client: AsyncClient):
        resp = await client.get("/api/templates")
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")

    async def test_get_slot_editors_html(self, client: AsyncClient):
        resp = await client.get("/api/templates/car_01/slots")
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")

    async def test_patch_slot_returns_preview(self, client: AsyncClient):
        resp = await client.patch(
            "/api/slots/car_01/headline",
            data={"content": "Test Value"},
        )
        assert resp.status_code == 200
        assert "svg" in resp.text.lower() or "preview" in resp.text.lower()

    async def test_patch_image_slot_as_dict(self, client: AsyncClient):
        """Patching image slot stores dict and re-renders preview."""
        resp = await client.patch(
            "/api/slots/car_01/hero_image",
            data={"content": "https://example.com/car.jpg", "slot_type": "image", "prompt": "A red car"},
        )
        assert resp.status_code == 200

    async def test_patch_button_slot_as_dict(self, client: AsyncClient):
        """Patching button slot stores label/colors dict."""
        resp = await client.patch(
            "/api/slots/car_01/cta_button",
            data={"content": "Buy Now", "slot_type": "button", "bg_color": "#ff0000", "text_color": "#fff"},
        )
        assert resp.status_code == 200

    async def test_preview_endpoint(self, client: AsyncClient):
        resp = await client.get("/api/preview/car_01")
        assert resp.status_code == 200
        assert "svg" in resp.text.lower()

    async def test_generate_after_filling_slots(self, client: AsyncClient):
        """Generate endpoint should return HTML progress partial."""
        await client.patch("/api/slots/car_01/headline", data={"content": "Sale"})
        await client.patch("/api/slots/car_01/hero_image", data={"content": "https://example.com/car.jpg"})
        await client.patch("/api/slots/car_01/cta_button", data={"content": "Buy"})
        resp = await client.post("/api/generate/car_01")
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")
