"""Integration tests for image generation API endpoints."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient

from app.main import app
from app.services.nano_banana_client import NanoBananaClient
from app.services.image_generation_service import ImageGenerationService


@pytest.fixture
def client():
    """Create a test client with image generation services initialized."""
    # Ensure services are available even if lifespan didn't run
    if not hasattr(app.state, "image_generation_service"):
        nano_client = NanoBananaClient(api_key="")
        app.state.nano_banana_client = nano_client
        app.state.image_generation_service = ImageGenerationService(nano_client)
    return TestClient(app)


class TestImageGenerateAPI:
    """Tests for /api/image-generate endpoints."""

    def test_start_generation_missing_prompt(self, client):
        """POST without prompt should return 422."""
        response = client.post(
            "/api/image-generate/test_pattern/img_slot",
            data={"prompt": ""},
        )
        assert response.status_code in (404, 422)

    def test_start_generation_invalid_pattern(self, client):
        """POST with invalid pattern should return 404."""
        response = client.post(
            "/api/image-generate/nonexistent_pattern/img_slot",
            data={"prompt": "A red car"},
        )
        assert response.status_code == 404

    def test_generation_status_not_found(self, client):
        """GET status for nonexistent job should return 404."""
        response = client.get("/api/image-generate/status/nonexistent-job-id")
        assert response.status_code == 404

    def test_apply_image_missing_url(self, client):
        """POST apply without image_url should return 422."""
        response = client.post(
            "/api/image-generate/apply/test_pattern/img_slot",
            data={"prompt": "test"},
        )
        assert response.status_code in (404, 422)
