"""Tests for NanoBananaClient with NanoBannaraPro2 support."""

import pytest
from unittest.mock import MagicMock, patch, AsyncMock

from app.services.nano_banana_client import NanoBananaClient


class TestNanoBananaClientV2:
    """Tests for NanoBannaraPro2 client features."""

    @pytest.fixture
    def client(self):
        return NanoBananaClient(api_key="test-key")

    def test_model_name_is_nano_banana_pro(self):
        """Model name should be gemini-3-pro-image-preview (Nano Banana Pro)."""
        from app.services.nano_banana_client import _MODEL_NAME
        assert "gemini-3-pro-image-preview" in _MODEL_NAME

    def test_build_prompt_without_user_prompt(self, client):
        """_build_prompt without user_prompt should work as before."""
        instruction = {
            "canvas": {"width": 1200, "height": 630, "background_color": "#FFF", "format": "png"},
            "layers": [
                {
                    "type": "text",
                    "text": {"content": "Hello", "font_size": 24, "color": "#000"},
                    "position": {"x": 10, "y": 20},
                }
            ],
        }
        prompt = client._build_prompt(instruction)
        assert "1200x630" in prompt
        assert "Hello" in prompt

    def test_build_prompt_with_user_prompt(self, client):
        """_build_prompt with user_prompt should include user direction."""
        instruction = {
            "canvas": {"width": 1024, "height": 1024},
            "layers": [],
        }
        prompt = client._build_prompt(instruction, user_prompt="赤いスポーツカー")
        assert "赤いスポーツカー" in prompt

    @pytest.mark.asyncio
    async def test_submit_render_creates_job(self, client):
        """submit_render should create a job and return job_id."""
        job_id = await client.submit_render({"canvas": {}, "layers": []})
        assert isinstance(job_id, str)
        assert len(job_id) > 0

    @pytest.mark.asyncio
    async def test_submit_render_with_user_prompt(self, client):
        """submit_render with user_prompt should store it."""
        job_id = await client.submit_render(
            {"canvas": {}, "layers": []},
            user_prompt="Beautiful sunset"
        )
        job = client._jobs.get(job_id)
        assert job is not None

    @pytest.mark.asyncio
    async def test_get_status_not_found(self, client):
        """get_status for nonexistent job should return not_found."""
        status = await client.get_status("nonexistent")
        assert status["status"] == "not_found"

    @pytest.mark.asyncio
    async def test_get_result_empty_for_nonexistent(self, client):
        """get_result for nonexistent job should return empty bytes."""
        result = await client.get_result("nonexistent")
        assert result == b""

    @pytest.mark.asyncio
    async def test_generate_image_from_prompt(self, client):
        """generate_image_from_prompt should create a job."""
        job_id = await client.generate_image_from_prompt(
            prompt="A red car",
            width=512,
            height=512,
        )
        assert isinstance(job_id, str)
        status = await client.get_status(job_id)
        assert status["status"] in ("queued", "processing", "completed", "failed")

    @pytest.mark.asyncio
    async def test_generate_image_from_prompt_default_dimensions(self, client):
        """generate_image_from_prompt should use default 1024x1024."""
        job_id = await client.generate_image_from_prompt(prompt="Test")
        assert isinstance(job_id, str)

    @pytest.mark.asyncio
    async def test_close_clears_jobs(self, client):
        """close should clear all jobs."""
        await client.submit_render({"canvas": {}, "layers": []})
        assert len(client._jobs) > 0
        await client.close()
        assert len(client._jobs) == 0
