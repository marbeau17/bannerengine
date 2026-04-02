"""Tests for the banner generation pipeline: SVG to PNG conversion."""

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


def _make_template() -> BannerTemplate:
    return BannerTemplate(
        meta=TemplateMeta(
            category="test", pattern_id="gen_01",
            pattern_name="Gen Test", width=400, height=200,
        ),
        design=TemplateDesign(
            background_type="solid", background_value="#ffffff",
            primary_color="#000", font_style="default",
        ),
        slots=[
            Slot(id="title", type=SlotType.TEXT, x=10, y=10, width=80, height=20, required=True),
        ],
        rules=[],
    )


class TestSvgToPng:
    def test_svg_to_png_returns_bytes(self):
        from app.routers.generate import _svg_to_png
        renderer = SvgRenderer()
        tmpl = _make_template()
        svg = renderer.render(tmpl, {"title": "Hello"})
        png = _svg_to_png(svg, 400, 200)
        assert isinstance(png, bytes)
        assert len(png) > 0
        # PNG magic bytes
        assert png[:4] == b"\x89PNG"

    def test_svg_to_png_with_empty_svg(self):
        from app.routers.generate import _svg_to_png
        svg = '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100"><rect width="100" height="100" fill="red"/></svg>'
        png = _svg_to_png(svg, 100, 100)
        assert png[:4] == b"\x89PNG"

    def test_svg_to_png_respects_dimensions(self):
        from app.routers.generate import _svg_to_png
        from PIL import Image
        import io
        svg = '<svg xmlns="http://www.w3.org/2000/svg" width="200" height="100"><rect width="200" height="100" fill="blue"/></svg>'
        png = _svg_to_png(svg, 200, 100)
        img = Image.open(io.BytesIO(png))
        assert img.width == 200
        assert img.height == 100


class TestRenderBanner:
    @pytest.mark.asyncio
    async def test_render_banner_creates_file(self, tmp_path, monkeypatch):
        import os
        from app.routers.generate import _render_banner, _jobs, OUTPUT_DIR

        monkeypatch.setattr("app.routers.generate.OUTPUT_DIR", str(tmp_path))

        job_id = "test-job-123"
        _jobs[job_id] = {
            "job_id": job_id, "status": "processing",
            "progress": 0, "file_url": None,
        }

        renderer = SvgRenderer()
        tmpl = _make_template()
        svg = renderer.render(tmpl, {"title": "Test"})

        await _render_banner(job_id, svg, 400, 200)

        assert _jobs[job_id]["status"] == "completed"
        assert _jobs[job_id]["progress"] == 100
        assert _jobs[job_id]["file_url"] is not None

        # Check the file was actually written
        filename = f"{job_id}.png"
        filepath = tmp_path / filename
        assert filepath.exists()
        assert filepath.stat().st_size > 0

    @pytest.mark.asyncio
    async def test_render_banner_handles_error(self, monkeypatch):
        from app.routers.generate import _render_banner, _jobs

        job_id = "test-fail-job"
        _jobs[job_id] = {
            "job_id": job_id, "status": "processing",
            "progress": 0, "file_url": None,
        }

        # Pass invalid SVG that will fail
        monkeypatch.setattr("app.routers.generate.OUTPUT_DIR", "/nonexistent/path")

        await _render_banner(job_id, "<invalid>", 100, 100)

        assert _jobs[job_id]["status"] == "failed"
        assert _jobs[job_id].get("error") is not None
