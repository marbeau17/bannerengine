"""NanoBannaraPro2 client using Google GenAI SDK (nano-bannara-pro-2 model)."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import uuid
from typing import Any

logger = logging.getLogger(__name__)

_MODEL_NAME = "gemini-3-pro-image-preview"


class NanoBananaClient:
    """Client for NanoBannaraPro2 image generation via Google GenAI.

    Uses the ``google.generativeai`` (genai) SDK with the
    ``nano-bannara-pro-2`` model to generate banner images from
    render instructions.
    """

    def __init__(self, api_key: str, api_url: str = "") -> None:
        self._api_key = api_key
        self._model = None
        self._jobs: dict[str, dict[str, Any]] = {}

    def _get_model(self):
        """Lazily initialize the GenAI model."""
        if self._model is None:
            import google.generativeai as genai

            genai.configure(api_key=self._api_key)
            self._model = genai.GenerativeModel(_MODEL_NAME)
        return self._model

    async def submit_render(
        self, instruction: dict, user_prompt: str | None = None
    ) -> str:
        """Submit a render instruction and return a job_id.

        The render instruction is converted to a prompt for the
        nano-bannara-pro-2 model. Generation runs asynchronously.
        """
        job_id = str(uuid.uuid4())
        self._jobs[job_id] = {
            "status": "queued",
            "progress": 0,
            "instruction": instruction,
            "user_prompt": user_prompt,
            "result": None,
            "error": None,
        }

        # Launch generation in background
        asyncio.create_task(self._generate(job_id, instruction, user_prompt))

        return job_id

    async def get_status(self, job_id: str) -> dict:
        """Get the current status of a generation job."""
        job = self._jobs.get(job_id)
        if job is None:
            return {"status": "not_found", "progress": 0}
        return {
            "status": job["status"],
            "progress": job["progress"],
            "error": job.get("error"),
        }

    async def get_result(self, job_id: str) -> bytes:
        """Get the generated image bytes for a completed job."""
        job = self._jobs.get(job_id)
        if job is None or job["result"] is None:
            return b""
        return job["result"]

    async def _generate(
        self, job_id: str, instruction: dict, user_prompt: str | None = None
    ) -> None:
        """Run the actual generation via GenAI."""
        job = self._jobs[job_id]
        try:
            job["status"] = "processing"
            job["progress"] = 10

            model = self._get_model()

            # Build the generation prompt from the render instruction
            prompt = self._build_prompt(instruction, user_prompt=user_prompt)

            job["progress"] = 30

            # Call the model
            response = await asyncio.to_thread(
                model.generate_content, prompt
            )

            job["progress"] = 80

            # Extract image data from response
            if response.parts:
                for part in response.parts:
                    if hasattr(part, "inline_data") and part.inline_data:
                        job["result"] = part.inline_data.data
                        break

            if job["result"] is None:
                # If no image returned, store the text response
                job["error"] = "No image generated"

            job["progress"] = 100
            job["status"] = "completed"

        except Exception as exc:
            logger.error("Generation failed for job %s: %s", job_id, exc)
            job["status"] = "failed"
            job["error"] = str(exc)
            job["progress"] = 0

    @staticmethod
    def _build_prompt(
        instruction: dict, *, user_prompt: str | None = None
    ) -> str:
        """Convert a render instruction dict into a text prompt."""
        canvas = instruction.get("canvas", {})
        layers = instruction.get("layers", [])

        parts = []

        if user_prompt:
            parts.append(f"User creative direction: {user_prompt}")

        parts.extend([
            f"Generate a banner image with dimensions {canvas.get('width', 1200)}x{canvas.get('height', 630)} pixels.",
            f"Background color: {canvas.get('background_color', '#FFFFFF')}.",
            f"Output format: {canvas.get('format', 'png')}.",
        ])

        for layer in layers:
            layer_type = layer.get("type", "")
            if layer_type == "text":
                text_info = layer.get("text", {})
                parts.append(
                    f"Text layer: \"{text_info.get('content', '')}\" at position "
                    f"({layer.get('position', {}).get('x', 0)}, {layer.get('position', {}).get('y', 0)}), "
                    f"font-size {text_info.get('font_size', 16)}px, color {text_info.get('color', '#000000')}."
                )
            elif layer_type == "image":
                parts.append(
                    f"Image layer at position "
                    f"({layer.get('position', {}).get('x', 0)}, {layer.get('position', {}).get('y', 0)}), "
                    f"size {layer.get('size', {}).get('width', 100)}x{layer.get('size', {}).get('height', 100)}."
                )

        return "\n".join(parts)

    async def generate_image_from_prompt(
        self, prompt: str, width: int = 1024, height: int = 1024
    ) -> str:
        """Generate an image from a plain text prompt.

        Creates a simplified render instruction with the given canvas
        dimensions and delegates to :meth:`submit_render`.

        Returns the job_id for status polling / result retrieval.
        """
        instruction = {
            "canvas": {
                "width": width,
                "height": height,
            },
        }
        job_id = await self.submit_render(instruction, user_prompt=prompt)
        return job_id

    async def close(self) -> None:
        """Clean up resources."""
        self._jobs.clear()
