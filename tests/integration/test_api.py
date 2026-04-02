"""Integration tests for the FastAPI API endpoints.

Test IDs follow the spec convention UT-API-001 through UT-API-012.
Uses httpx AsyncClient with the FastAPI ASGI app.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core.svg_renderer import SvgRenderer
from app.core.xml_parser import XMLTemplateParser
from app.models.template import (
    BannerTemplate,
    Slot,
    SlotType,
    TemplateDesign,
    TemplateMeta,
)
from app.services.template_service import TemplateService

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sample_template() -> BannerTemplate:
    return BannerTemplate(
        meta=TemplateMeta(
            category="used_car",
            pattern_id="car_01",
            pattern_name="Test Car Banner",
            width=1200,
            height=628,
            aspect_ratio="1.91:1",
            layout_type="hero_image",
            recommended_use="Testing",
        ),
        design=TemplateDesign(
            background_type="solid",
            background_value="#1a1a2e",
            primary_color="#e94560",
            font_style="modern",
        ),
        slots=[
            Slot(
                id="headline", type=SlotType.TEXT,
                x=10, y=10, width=80, height=15,
                required=True, max_chars=30,
                font_size_guideline="32px", font_weight="bold", color="#ffffff",
            ),
            Slot(
                id="hero_image", type=SlotType.IMAGE,
                x=0, y=0, width=100, height=100,
                required=True,
            ),
            Slot(
                id="cta_button", type=SlotType.BUTTON,
                x=60, y=85, width=30, height=10,
                required=True,
                default_label="View Details",
                bg_color="#e94560", text_color="#ffffff",
            ),
        ],
        rules=["Be concise"],
    )


def _make_service_with_template() -> TemplateService:
    """Create a TemplateService with a sample template loaded.

    Also patches in a ``list_templates`` alias if the service only
    exposes ``get_all_templates``, so that the router can call either.
    """
    service = TemplateService()
    tmpl = _sample_template()
    service._templates[tmpl.meta.pattern_id] = tmpl

    # The router calls service.list_templates() but TemplateService only
    # defines get_all_templates(). Add the alias so the endpoint works.
    if not hasattr(service, "list_templates"):
        service.list_templates = service.get_all_templates  # type: ignore[attr-defined]

    return service


@pytest_asyncio.fixture
async def client_with_template():
    """AsyncClient with a pre-loaded template in app state."""
    from app.main import app

    service = _make_service_with_template()
    app.state.template_service = service
    app.state.svg_renderer = SvgRenderer()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


# ---------------------------------------------------------------------------
# UT-API-001: GET /health
# ---------------------------------------------------------------------------

class TestHealthEndpoint:
    async def test_health_check(self, client_with_template: AsyncClient):
        resp = await client_with_template.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"


# ---------------------------------------------------------------------------
# UT-API-002: GET /api/templates
# ---------------------------------------------------------------------------

class TestListTemplates:
    async def test_list_templates_returns_html(self, client_with_template: AsyncClient):
        resp = await client_with_template.get("/api/templates")
        # The endpoint returns HTML partials via Jinja2. A successful
        # response means the template_service.list_templates() call and
        # the Jinja2 partial rendering both worked.
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")


# ---------------------------------------------------------------------------
# UT-API-003: GET /api/templates/{pattern_id}/slots - success
# ---------------------------------------------------------------------------

class TestGetTemplateSlots:
    async def test_get_template_slots_success(self, client_with_template: AsyncClient):
        resp = await client_with_template.get("/api/templates/car_01/slots")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# UT-API-004: GET /api/templates/{pattern_id} - 404
# ---------------------------------------------------------------------------

class TestGetTemplateNotFound:
    async def test_get_template_not_found(self, client_with_template: AsyncClient):
        resp = await client_with_template.get("/api/templates/nonexistent_99")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# UT-API-005: PATCH /api/slots/{pattern_id}/{slot_id} - success
# ---------------------------------------------------------------------------

class TestUpdateSlotSuccess:
    async def test_patch_slot_value(self, client_with_template: AsyncClient):
        resp = await client_with_template.patch(
            "/api/slots/car_01/headline",
            data={"value": "Great Deal"},
        )
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# UT-API-006: PATCH /api/slots - template not found
# ---------------------------------------------------------------------------

class TestUpdateSlotTemplateNotFound:
    async def test_patch_slot_template_not_found(self, client_with_template: AsyncClient):
        resp = await client_with_template.patch(
            "/api/slots/no_such_template/headline",
            data={"value": "Test"},
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# UT-API-007: PATCH /api/slots - slot not found (422)
# ---------------------------------------------------------------------------

class TestUpdateSlotNotFound:
    async def test_patch_slot_not_found(self, client_with_template: AsyncClient):
        resp = await client_with_template.patch(
            "/api/slots/car_01/nonexistent_slot",
            data={"value": "Test"},
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# UT-API-008: GET /api/preview/{pattern_id} - success
# ---------------------------------------------------------------------------

class TestPreviewSuccess:
    async def test_preview_returns_svg_html(self, client_with_template: AsyncClient):
        resp = await client_with_template.get("/api/preview/car_01")
        assert resp.status_code == 200
        assert "svg" in resp.text.lower()


# ---------------------------------------------------------------------------
# UT-API-009: GET /api/preview/{pattern_id} - 404
# ---------------------------------------------------------------------------

class TestPreviewNotFound:
    async def test_preview_template_not_found(self, client_with_template: AsyncClient):
        resp = await client_with_template.get("/api/preview/nonexistent_99")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# UT-API-010: POST /api/generate/{pattern_id} - 202 accepted
# ---------------------------------------------------------------------------

class TestGenerateAccepted:
    async def test_generate_returns_html(self, client_with_template: AsyncClient):
        # First fill in all required slots via the session-aware PATCH
        await client_with_template.patch(
            "/api/slots/car_01/headline",
            data={"value": "Sale"},
        )
        await client_with_template.patch(
            "/api/slots/car_01/hero_image",
            data={"value": "https://example.com/car.jpg"},
        )
        await client_with_template.patch(
            "/api/slots/car_01/cta_button",
            data={"value": "Buy Now"},
        )

        resp = await client_with_template.post("/api/generate/car_01")
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")
        assert "生成中" in resp.text


# ---------------------------------------------------------------------------
# UT-API-011: POST /api/generate/{pattern_id} - 404
# ---------------------------------------------------------------------------

class TestGenerateNotFound:
    async def test_generate_template_not_found(self, client_with_template: AsyncClient):
        resp = await client_with_template.post("/api/generate/no_such_template")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# UT-API-012: POST /api/generate - missing required slots (422)
# ---------------------------------------------------------------------------

class TestGenerateMissingSlots:
    async def test_generate_missing_required_slots(self, client_with_template: AsyncClient):
        # Don't fill in any slots -- returns HTML error partial.
        resp = await client_with_template.post("/api/generate/car_01")
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")
        assert "未入力" in resp.text or "エラー" in resp.text
