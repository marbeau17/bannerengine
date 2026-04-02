"""Tests for TemplateService: loading, querying, searching, categories."""

from __future__ import annotations

import os
import tempfile

import pytest

from app.core.exceptions import TemplateNotFoundError
from app.models.template import (
    BannerTemplate,
    Slot,
    SlotType,
    TemplateDesign,
    TemplateMeta,
)
from app.services.template_service import CATEGORY_DISPLAY_NAMES, TemplateService


def _make_template(pattern_id: str, category: str, name: str = "Test") -> BannerTemplate:
    return BannerTemplate(
        meta=TemplateMeta(
            category=category,
            pattern_id=pattern_id,
            pattern_name=name,
            width=800,
            height=400,
            layout_type="hero",
            recommended_use="testing",
        ),
        design=TemplateDesign(
            background_type="solid",
            background_value="#fff",
            primary_color="#000",
            font_style="default",
        ),
        slots=[],
        rules=[],
    )


@pytest.fixture
def service() -> TemplateService:
    svc = TemplateService()
    svc._templates["car_01"] = _make_template("car_01", "used_car", "Single Car")
    svc._templates["car_02"] = _make_template("car_02", "used_car", "Grid Car")
    svc._templates["app_01"] = _make_template("app_01", "apparel", "Season Visual")
    return svc


class TestGetTemplate:
    def test_get_existing(self, service: TemplateService):
        t = service.get_template("car_01")
        assert t.meta.pattern_id == "car_01"

    def test_get_not_found_raises(self, service: TemplateService):
        with pytest.raises(TemplateNotFoundError):
            service.get_template("nonexistent")


class TestGetAllTemplates:
    def test_returns_all(self, service: TemplateService):
        all_t = service.get_all_templates()
        assert len(all_t) == 3

    def test_list_templates_alias(self, service: TemplateService):
        assert service.list_templates() == service.get_all_templates()


class TestGetCategories:
    def test_returns_category_counts(self, service: TemplateService):
        cats = service.get_categories()
        cat_map = {c["key"]: c for c in cats}
        assert cat_map["used_car"]["count"] == 2
        assert cat_map["apparel"]["count"] == 1

    def test_display_names(self, service: TemplateService):
        cats = service.get_categories()
        cat_map = {c["key"]: c for c in cats}
        assert cat_map["used_car"]["display_name"] == CATEGORY_DISPLAY_NAMES["used_car"]
        assert cat_map["apparel"]["display_name"] == CATEGORY_DISPLAY_NAMES["apparel"]

    def test_unknown_category_uses_key(self):
        svc = TemplateService()
        svc._templates["x"] = _make_template("x", "unknown_cat")
        cats = svc.get_categories()
        assert cats[0]["display_name"] == "unknown_cat"


class TestGetTemplatesByCategory:
    def test_filter_by_category(self, service: TemplateService):
        cars = service.get_templates_by_category("used_car")
        assert len(cars) == 2
        assert all(t.meta.category == "used_car" for t in cars)

    def test_empty_category(self, service: TemplateService):
        result = service.get_templates_by_category("ramen")
        assert result == []


class TestSearchTemplates:
    def test_search_by_name(self, service: TemplateService):
        results = service.search_templates("Single")
        assert len(results) == 1
        assert results[0].meta.pattern_id == "car_01"

    def test_search_by_category(self, service: TemplateService):
        results = service.search_templates("apparel")
        assert len(results) == 1

    def test_search_by_recommended_use(self, service: TemplateService):
        results = service.search_templates("testing")
        assert len(results) == 3

    def test_search_case_insensitive(self, service: TemplateService):
        results = service.search_templates("SINGLE")
        assert len(results) == 1

    def test_search_no_match(self, service: TemplateService):
        results = service.search_templates("zzzzz")
        assert results == []

    def test_search_japanese_display_name(self, service: TemplateService):
        results = service.search_templates("中古自動車")
        assert len(results) == 2


class TestLoadFromDirectory:
    def test_loads_xml_templates(self):
        svc = TemplateService()
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        svc.load_templates_from_directory(base_dir)
        all_t = svc.get_all_templates()
        assert len(all_t) > 0

    def test_nonexistent_directory(self):
        svc = TemplateService()
        svc.load_templates_from_directory("/nonexistent/path")
        assert svc.get_all_templates() == []

    def test_skips_bad_xml(self, tmp_path):
        xml_dir = tmp_path / "xml_templates"
        xml_dir.mkdir()
        (xml_dir / "bad.xml").write_text("<not-valid>")
        svc = TemplateService()
        svc.load_templates_from_directory(str(tmp_path))
        assert svc.get_all_templates() == []
