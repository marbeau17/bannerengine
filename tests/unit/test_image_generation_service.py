"""Tests for ImageGenerationService."""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.image_generation_service import ImageGenerationService


class MockNanoBananaClient:
    """Mock NanoBananaClient for testing."""

    def __init__(self):
        self.submitted_jobs = {}
        self._counter = 0

    async def generate_image_from_prompt(self, prompt: str, width: int = 1024, height: int = 1024) -> str:
        self._counter += 1
        job_id = f"mock-job-{self._counter}"
        self.submitted_jobs[job_id] = {
            "prompt": prompt,
            "width": width,
            "height": height,
            "status": "completed",
            "progress": 100,
        }
        return job_id

    async def get_status(self, job_id: str) -> dict:
        job = self.submitted_jobs.get(job_id, {})
        return {
            "status": job.get("status", "completed"),
            "progress": job.get("progress", 100),
        }

    async def get_result(self, job_id: str) -> bytes:
        return b"\x89PNG\r\n\x1a\n" + b"\x00" * 100  # Minimal PNG-like bytes


class TestImageGenerationService:
    """Tests for ImageGenerationService."""

    @pytest.fixture
    def mock_client(self):
        return MockNanoBananaClient()

    @pytest.fixture
    def service(self, mock_client):
        return ImageGenerationService(mock_client)

    @pytest.mark.asyncio
    async def test_generate_for_slot_returns_job_id(self, service):
        """generate_for_slot should return a job_id string."""
        job_id = await service.generate_for_slot(
            prompt="A red car",
            pattern_id="test_pattern",
            slot_id="img_slot_1",
        )
        assert isinstance(job_id, str)
        assert len(job_id) > 0

    @pytest.mark.asyncio
    async def test_get_job_status_not_found(self, service):
        """get_job_status should return not_found for unknown jobs."""
        status = await service.get_job_status("nonexistent-job")
        assert status["status"] == "not_found"

    @pytest.mark.asyncio
    async def test_get_job_status_queued(self, service):
        """get_job_status should return queued status for new jobs."""
        job_id = await service.generate_for_slot(
            prompt="A sunset",
            pattern_id="p1",
            slot_id="s1",
        )
        # Immediately after creation, status should exist
        status = await service.get_job_status(job_id)
        assert status["job_id"] == job_id
        assert status["pattern_id"] == "p1"
        assert status["slot_id"] == "s1"

    @pytest.mark.asyncio
    async def test_generate_stores_prompt(self, service):
        """Job should store the prompt."""
        job_id = await service.generate_for_slot(
            prompt="赤いスポーツカー",
            pattern_id="p1",
            slot_id="s1",
        )
        job = service._jobs.get(job_id)
        assert job is not None
        assert job["prompt"] == "赤いスポーツカー"

    @pytest.mark.asyncio
    async def test_generate_completes(self, service):
        """Job should eventually complete with an image URL."""
        job_id = await service.generate_for_slot(
            prompt="A test image",
            pattern_id="p1",
            slot_id="s1",
            width=512,
            height=512,
        )
        # Wait for background task to complete
        await asyncio.sleep(2)
        status = await service.get_job_status(job_id)
        assert status["status"] == "completed"
        assert status["image_url"] is not None
        assert status["image_url"].startswith("/static/generated/")

    @pytest.mark.asyncio
    async def test_generate_custom_dimensions(self, mock_client, service):
        """Should pass custom dimensions to the client."""
        job_id = await service.generate_for_slot(
            prompt="Test",
            pattern_id="p1",
            slot_id="s1",
            width=800,
            height=600,
        )
        # Wait for the background task to submit to client
        await asyncio.sleep(1)
        # Check the client received the right dimensions
        for cjob in mock_client.submitted_jobs.values():
            if cjob["prompt"] == "Test":
                assert cjob["width"] == 800
                assert cjob["height"] == 600
