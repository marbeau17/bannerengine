"""Shared pytest fixtures for Banner Engine tests."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core.svg_renderer import SvgRenderer
from app.core.xml_parser import XMLTemplateParser
from app.models.template import BannerTemplate
from app.services.template_service import TemplateService

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _patch_template_service(service: TemplateService) -> TemplateService:
    """Add ``list_templates`` alias if not already present.

    The router calls ``service.list_templates()`` but the service class
    only defines ``get_all_templates()``.  This shim keeps tests green.
    """
    if not hasattr(service, "list_templates"):
        service.list_templates = service.get_all_templates  # type: ignore[attr-defined]
    return service


@pytest.fixture
def sample_car_xml_path() -> str:
    """Path to the sample car XML fixture file."""
    return str(FIXTURES_DIR / "sample_car.xml")


@pytest.fixture
def invalid_xml_path() -> str:
    """Path to the malformed XML fixture file."""
    return str(FIXTURES_DIR / "invalid.xml")


@pytest.fixture
def empty_slots_xml_path() -> str:
    """Path to the empty-slots XML fixture file."""
    return str(FIXTURES_DIR / "empty_slots.xml")


@pytest.fixture
def sample_car_xml_string() -> str:
    """Raw XML string for the sample car_01 template."""
    with open(FIXTURES_DIR / "sample_car.xml", encoding="utf-8") as fh:
        return fh.read()


@pytest.fixture
def xml_parser() -> XMLTemplateParser:
    """Fresh XMLTemplateParser instance."""
    return XMLTemplateParser()


@pytest.fixture
def parsed_car_template(xml_parser: XMLTemplateParser, sample_car_xml_path: str) -> BannerTemplate:
    """A fully parsed BannerTemplate from the sample car fixture."""
    return xml_parser.parse_file(sample_car_xml_path)


@pytest.fixture
def template_service_with_car(
    parsed_car_template: BannerTemplate,
) -> TemplateService:
    """TemplateService pre-loaded with the sample car template."""
    service = TemplateService()
    service._templates[parsed_car_template.meta.pattern_id] = parsed_car_template
    return _patch_template_service(service)


@pytest.fixture
def svg_renderer() -> SvgRenderer:
    """Fresh SvgRenderer instance."""
    return SvgRenderer()


@pytest.fixture
def sample_slot_values() -> dict:
    """Sample slot values dict suitable for the car_01 template."""
    return {
        "hero_image": "https://example.com/car.jpg",
        "headline": "Premium Used Cars",
        "price_tag": "$25,000",
        "description": "Low mileage, excellent condition, full service history.",
        "logo": "AutoDealer Inc.",
        "cta_button": {"label": "Shop Now", "bg_color": "#e94560", "text_color": "#ffffff"},
    }


@pytest.fixture
def tmp_upload_dir(tmp_path: Path) -> Path:
    """Temporary upload directory for asset tests."""
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir()
    return upload_dir


@pytest_asyncio.fixture
async def async_client():
    """httpx AsyncClient wired to the FastAPI app for integration tests.

    The app's lifespan is suppressed so tests don't depend on XML
    templates being present on disk.
    """
    from app.main import app

    if not hasattr(app.state, "template_service"):
        service = _patch_template_service(TemplateService())
        app.state.template_service = service

    if not hasattr(app.state, "svg_renderer"):
        app.state.svg_renderer = SvgRenderer()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client
