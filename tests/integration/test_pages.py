"""Integration tests for page rendering routes (home, editor)."""

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
        ),
        design=TemplateDesign(
            background_type="solid", background_value="#1a1a2e",
            primary_color="#e94560", font_style="modern",
        ),
        slots=[
            Slot(id="headline", type=SlotType.TEXT, x=10, y=10, width=80, height=15, required=True),
            Slot(id="photo", type=SlotType.IMAGE, x=0, y=30, width=100, height=70, required=True),
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


class TestHomePage:
    async def test_home_returns_html(self, client: AsyncClient):
        resp = await client.get("/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")
        assert "Banner Engine" in resp.text

    async def test_home_lists_categories(self, client: AsyncClient):
        resp = await client.get("/")
        assert resp.status_code == 200
        assert "used_car" in resp.text or "中古自動車" in resp.text


class TestEditorPage:
    async def test_editor_returns_html(self, client: AsyncClient):
        resp = await client.get("/editor/car_01")
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")

    async def test_editor_contains_slots(self, client: AsyncClient):
        resp = await client.get("/editor/car_01")
        assert "headline" in resp.text
        assert "photo" in resp.text

    async def test_editor_contains_preview(self, client: AsyncClient):
        resp = await client.get("/editor/car_01")
        assert "preview-canvas" in resp.text

    async def test_editor_not_found(self, client: AsyncClient):
        resp = await client.get("/editor/nonexistent")
        assert resp.status_code == 404


class TestTemplateRoutes:
    async def test_categories_endpoint(self, client: AsyncClient):
        resp = await client.get("/api/templates/categories")
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")

    async def test_template_detail(self, client: AsyncClient):
        resp = await client.get("/api/templates/car_01")
        assert resp.status_code == 200

    async def test_template_detail_not_found(self, client: AsyncClient):
        resp = await client.get("/api/templates/nonexistent")
        assert resp.status_code == 404

    async def test_list_with_category_filter(self, client: AsyncClient):
        resp = await client.get("/api/templates?category=used_car")
        assert resp.status_code == 200

    async def test_list_with_search(self, client: AsyncClient):
        resp = await client.get("/api/templates?q=Car")
        assert resp.status_code == 200

    async def test_list_empty_search(self, client: AsyncClient):
        resp = await client.get("/api/templates?q=zzzznonexistent")
        assert resp.status_code == 200
        assert "テンプレートが見つかりませんでした" in resp.text


class TestGenerateFlow:
    async def test_generate_missing_slots_shows_error_html(self, client: AsyncClient):
        resp = await client.post("/api/generate/car_01")
        assert resp.status_code == 200
        assert "未入力" in resp.text

    async def test_generate_success_shows_progress(self, client: AsyncClient):
        await client.patch("/api/slots/car_01/headline", data={"content": "Sale"})
        await client.patch("/api/slots/car_01/photo", data={"content": "https://example.com/img.jpg"})
        resp = await client.post("/api/generate/car_01")
        assert resp.status_code == 200
        assert "生成中" in resp.text

    async def test_progress_poll(self, client: AsyncClient):
        """Progress endpoint returns HTML for unknown job."""
        resp = await client.get("/api/generate/progress/nonexistent-id")
        assert resp.status_code == 200
        assert "エラー" in resp.text
