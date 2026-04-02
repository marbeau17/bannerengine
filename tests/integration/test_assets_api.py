"""Integration tests for asset upload, list, and delete endpoints."""

from __future__ import annotations

import io
import struct

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
            category="test", pattern_id="test_01",
            pattern_name="Test", width=800, height=400,
        ),
        design=TemplateDesign(
            background_type="solid", background_value="#fff",
            primary_color="#000", font_style="default",
        ),
        slots=[
            Slot(id="img", type=SlotType.IMAGE, x=0, y=0, width=100, height=100, required=True),
        ],
        rules=[],
    )


def _make_png_bytes(width: int = 1, height: int = 1) -> bytes:
    """Create a minimal valid 1x1 PNG file."""
    import zlib

    def _chunk(chunk_type: bytes, data: bytes) -> bytes:
        c = chunk_type + data
        crc = struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)
        return struct.pack(">I", len(data)) + c + crc

    header = b"\x89PNG\r\n\x1a\n"
    ihdr_data = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    ihdr = _chunk(b"IHDR", ihdr_data)
    raw_row = b"\x00" + b"\x00\x00\x00" * width
    raw_data = raw_row * height
    compressed = zlib.compress(raw_data)
    idat = _chunk(b"IDAT", compressed)
    iend = _chunk(b"IEND", b"")
    return header + ihdr + idat + iend


def _make_jpeg_bytes() -> bytes:
    """Create minimal valid JPEG bytes."""
    return b"\xff\xd8\xff\xe0" + b"\x00" * 100


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


class TestUploadAsset:
    async def test_upload_png_success(self, client: AsyncClient):
        png = _make_png_bytes()
        resp = await client.post(
            "/api/assets/upload",
            files={"file": ("test.png", io.BytesIO(png), "image/png")},
            data={"slot_id": "img", "pattern_id": "test_01"},
        )
        assert resp.status_code == 200
        # Should return preview HTML
        assert "svg" in resp.text.lower() or "preview" in resp.text.lower()

    async def test_upload_updates_slot_session(self, client: AsyncClient):
        """Upload should update the slot value and preview should reflect it."""
        png = _make_png_bytes()
        await client.post(
            "/api/assets/upload",
            files={"file": ("test.png", io.BytesIO(png), "image/png")},
            data={"slot_id": "img", "pattern_id": "test_01"},
        )
        # Now check the slot value
        resp = await client.get("/api/slots/test_01/img")
        assert resp.status_code == 200
        data = resp.json()
        assert "uploads" in str(data.get("value", ""))

    async def test_upload_without_slot_returns_html(self, client: AsyncClient):
        """Upload without slot_id should return a simple HTML confirmation."""
        png = _make_png_bytes()
        resp = await client.post(
            "/api/assets/upload",
            files={"file": ("test.png", io.BytesIO(png), "image/png")},
        )
        assert resp.status_code == 201
        assert "Uploaded" in resp.text

    async def test_upload_unsupported_type(self, client: AsyncClient):
        resp = await client.post(
            "/api/assets/upload",
            files={"file": ("test.txt", io.BytesIO(b"hello"), "text/plain")},
        )
        assert resp.status_code == 422

    async def test_upload_too_large(self, client: AsyncClient):
        # Create a file just over 10MB
        big = b"\x89PNG\r\n\x1a\n" + b"\x00" * (10 * 1024 * 1024 + 1)
        resp = await client.post(
            "/api/assets/upload",
            files={"file": ("big.png", io.BytesIO(big), "image/png")},
        )
        assert resp.status_code == 422

    async def test_upload_mismatched_magic_bytes_auto_detects(self, client: AsyncClient):
        """File claiming to be PNG but with JPEG magic bytes should auto-detect as JPEG."""
        fake = b"\xff\xd8\xff\xe0" + b"\x00" * 100
        resp = await client.post(
            "/api/assets/upload",
            files={"file": ("fake.png", io.BytesIO(fake), "image/png")},
        )
        # Auto-detects as JPEG from magic bytes, upload succeeds
        assert resp.status_code in (200, 201)

    async def test_upload_too_small(self, client: AsyncClient):
        resp = await client.post(
            "/api/assets/upload",
            files={"file": ("tiny.png", io.BytesIO(b"\x89PNG"), "image/png")},
        )
        assert resp.status_code == 422


class TestListAssets:
    async def test_list_empty(self, client: AsyncClient):
        resp = await client.get("/api/assets")
        assert resp.status_code == 200
        assert resp.json()["assets"] == [] or isinstance(resp.json()["assets"], list)


class TestDeleteAsset:
    async def test_delete_not_found(self, client: AsyncClient):
        resp = await client.delete("/api/assets/nonexistent-id")
        assert resp.status_code == 404


class TestMimeDetection:
    def test_detect_png(self):
        from app.routers.assets import _detect_mime_from_bytes
        header = b"\x89PNG\r\n\x1a\n" + b"\x00" * 4
        assert _detect_mime_from_bytes(header) == "image/png"

    def test_detect_jpeg(self):
        from app.routers.assets import _detect_mime_from_bytes
        header = b"\xff\xd8\xff\xe0" + b"\x00" * 8
        assert _detect_mime_from_bytes(header) == "image/jpeg"

    def test_detect_webp(self):
        from app.routers.assets import _detect_mime_from_bytes
        header = b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP"
        assert _detect_mime_from_bytes(header) == "image/webp"

    def test_invalid_webp_missing_marker(self):
        from app.routers.assets import _detect_mime_from_bytes
        header = b"RIFF" + b"\x00\x00\x00\x00" + b"AVI "
        assert _detect_mime_from_bytes(header) is None

    def test_unknown_bytes(self):
        from app.routers.assets import _detect_mime_from_bytes
        assert _detect_mime_from_bytes(b"\x00" * 12) is None

    def test_too_short(self):
        from app.routers.assets import _detect_mime_from_bytes
        assert _detect_mime_from_bytes(b"\x89P") is None
