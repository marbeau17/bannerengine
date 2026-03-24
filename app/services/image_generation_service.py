"""Image generation service for per-slot AI image generation using NanoBannaraPro2."""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from typing import Any

logger = logging.getLogger(__name__)


class ImageGenerationService:
    """Manages AI image generation for individual banner slots.

    Uses the NanoBananaClient to generate images from text prompts
    and saves results to the static/generated/ directory.
    """

    def __init__(self, nano_banana_client) -> None:
        self._client = nano_banana_client
        self._jobs: dict[str, dict[str, Any]] = {}
        self._output_dir = os.path.join("static", "generated")
        os.makedirs(self._output_dir, exist_ok=True)

    async def generate_for_slot(
        self,
        prompt: str,
        pattern_id: str,
        slot_id: str,
        width: int = 1024,
        height: int = 1024,
    ) -> str:
        """Start image generation for a specific slot.

        Args:
            prompt: Text prompt describing the desired image.
            pattern_id: The template pattern ID.
            slot_id: The slot ID to generate for.
            width: Desired image width.
            height: Desired image height.

        Returns:
            A job_id for tracking progress.
        """
        job_id = str(uuid.uuid4())
        self._jobs[job_id] = {
            "job_id": job_id,
            "pattern_id": pattern_id,
            "slot_id": slot_id,
            "prompt": prompt,
            "status": "queued",
            "progress": 0,
            "image_url": None,
            "error": None,
        }

        asyncio.create_task(self._run_generation(job_id, prompt, width, height))
        return job_id

    async def get_job_status(self, job_id: str) -> dict[str, Any]:
        """Get the current status of a generation job."""
        job = self._jobs.get(job_id)
        if job is None:
            return {"status": "not_found", "progress": 0}
        return {
            "job_id": job["job_id"],
            "status": job["status"],
            "progress": job["progress"],
            "image_url": job.get("image_url"),
            "error": job.get("error"),
            "pattern_id": job.get("pattern_id"),
            "slot_id": job.get("slot_id"),
        }

    async def _run_generation(
        self, job_id: str, prompt: str, width: int, height: int
    ) -> None:
        """Execute image generation in the background."""
        job = self._jobs[job_id]
        try:
            job["status"] = "processing"
            job["progress"] = 10

            # Submit to NanoBannaraPro2 via client
            client_job_id = await self._client.generate_image_from_prompt(
                prompt=prompt, width=width, height=height
            )

            # Poll for completion
            while True:
                status = await self._client.get_status(client_job_id)
                job["progress"] = min(status.get("progress", 0), 95)

                if status["status"] == "completed":
                    break
                elif status["status"] == "failed":
                    job["status"] = "failed"
                    job["error"] = status.get("error", "Generation failed")
                    return

                await asyncio.sleep(0.5)

            # Get the result image bytes
            image_bytes = await self._client.get_result(client_job_id)
            if not image_bytes:
                job["status"] = "failed"
                job["error"] = "No image data returned"
                return

            # Save to file
            filename = f"{job_id}.png"
            filepath = os.path.join(self._output_dir, filename)
            with open(filepath, "wb") as f:
                f.write(image_bytes)

            job["image_url"] = f"/static/generated/{filename}"
            job["progress"] = 100
            job["status"] = "completed"

        except Exception as exc:
            logger.error("Image generation failed for job %s: %s", job_id, exc)
            job["status"] = "failed"
            job["error"] = str(exc)
            job["progress"] = 0
