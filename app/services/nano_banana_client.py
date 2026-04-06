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

    async def analyze_banner(self, image_bytes: bytes, width: int, height: int, mime_type: str = "image/png") -> str:
        """Send a banner image to AI and get back XML template definition."""
        model = self._get_model()

        prompt = f"""Analyze this banner image and generate a valid XML template definition.

The banner is {width}x{height} pixels. Identify ALL visual elements: text regions, image regions, buttons, backgrounds.

Output ONLY valid XML in this exact format (no markdown, no explanation):

<banner_templates category="custom">
  <banner_template>
    <meta>
      <category>custom</category>
      <pattern_id>custom_001</pattern_id>
      <pattern_name>Custom Banner</pattern_name>
      <width>{width}</width>
      <height>{height}</height>
      <unit>px</unit>
      <aspect_ratio>auto</aspect_ratio>
      <layout_type>custom</layout_type>
      <recommended_use>Custom banner</recommended_use>
    </meta>
    <design>
      <background_type>color</background_type>
      <background_value>#FFFFFF</background_value>
      <primary_color>#000000</primary_color>
      <accent_color>#FF0000</accent_color>
      <font_style>NotoSansJP</font_style>
    </design>
    <slots>
      <!-- For each detected element, create a slot: -->
      <slot>
        <id>unique_id</id>
        <type>text OR image OR button</type>
        <x>percentage 0-100</x>
        <y>percentage 0-100</y>
        <width>percentage 0-100</width>
        <height>percentage 0-100</height>
        <description>what this element is</description>
        <required>true</required>
        <!-- For text: -->
        <max_chars>50</max_chars>
        <font_size_guideline>16px</font_size_guideline>
        <font_weight>normal OR bold</font_weight>
        <color>#000000</color>
        <!-- For text slots, include detected text in default_label: -->
        <default_label>detected text content here</default_label>
        <!-- For buttons: -->
        <default_label>button text</default_label>
        <bg_color>#000000</bg_color>
        <text_color>#FFFFFF</text_color>
      </slot>
    </slots>
    <rules>
      <rule>Custom banner template generated from uploaded image.</rule>
    </rules>
  </banner_template>
</banner_templates>

Important:
- Use percentage coordinates (0-100) for x, y, width, height relative to the canvas
- Detect the actual background color from the image
- Detect actual text content and include it in default_label
- Detect actual font sizes, weights, and colors
- Identify image regions as type "image"
- Identify button-like elements as type "button"
- Use descriptive Japanese for the description field
- Output ONLY the XML, nothing else"""

        image_part = {"mime_type": mime_type, "data": image_bytes}

        response = await asyncio.to_thread(
            model.generate_content, [prompt, image_part]
        )

        # Extract text response
        text = ""
        if response.parts:
            for part in response.parts:
                if hasattr(part, "text") and part.text:
                    text += part.text

        # Strip markdown code fences if present
        text = text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            # Remove first and last lines (code fences)
            lines = [l for l in lines if not l.strip().startswith("```")]
            text = "\n".join(lines)

        return text.strip()

    async def generate_from_reference(
        self,
        reference_image_bytes: bytes,
        instruction: dict,
        user_prompt: str | None = None,
        mode: str = "manual",
    ) -> str:
        """Generate a polished banner using a reference image + layout instructions.

        Args:
            mode: ``"manual"`` — strict, preserve exact text and layout;
                  ``"ai"`` — creative, use reference only as loose guidelines.
        """
        job_id = str(uuid.uuid4())
        self._jobs[job_id] = {
            "status": "queued",
            "progress": 0,
            "result": None,
            "error": None,
        }
        asyncio.create_task(
            self._generate_with_reference(job_id, reference_image_bytes, instruction, user_prompt, mode)
        )
        return job_id

    async def _generate_with_reference(
        self, job_id: str, reference_image_bytes: bytes, instruction: dict,
        user_prompt: str | None, mode: str = "manual",
    ) -> None:
        """Generate a polished banner from reference image + structured prompt."""
        job = self._jobs[job_id]
        try:
            job["status"] = "processing"
            job["progress"] = 10

            model = self._get_model()
            text_prompt = self._build_ai_enhance_prompt(instruction, user_prompt, mode=mode)

            job["progress"] = 30

            # Multimodal: text + reference image
            image_part = {"mime_type": "image/png", "data": reference_image_bytes}
            response = await asyncio.to_thread(
                model.generate_content, [text_prompt, image_part]
            )

            job["progress"] = 80

            if response.parts:
                for part in response.parts:
                    if hasattr(part, "inline_data") and part.inline_data:
                        job["result"] = part.inline_data.data
                        break

            if job["result"] is None:
                job["error"] = "No image generated by AI"

            job["progress"] = 100
            job["status"] = "completed"

        except Exception as exc:
            logger.error("AI reference generation failed for job %s: %s", job_id, exc)
            job["status"] = "failed"
            job["error"] = str(exc)
            job["progress"] = 0

    @staticmethod
    def _build_ai_enhance_prompt(
        instruction: dict,
        user_prompt: str | None = None,
        mode: str = "manual",
    ) -> str:
        """Build a prompt for AI-enhanced banner generation from a reference image.

        Args:
            mode: ``"manual"`` — strict mode (preserve exact text/layout);
                  ``"ai"`` — creative mode (use reference as loose guidelines).
        """
        canvas = instruction.get("canvas", {})
        layers = instruction.get("layers", [])

        if mode == "ai":
            # Creative mode: polish aesthetics freely but RESPECT physical layout structure.
            # Phase 4: We must constrain hallucinations — the AI may reimagine visuals
            # and typography style, but must NOT move, resize, or remove elements.
            parts = [
                "You are a creative banner designer. I'm providing a reference layout image.",
                f"Canvas: {canvas.get('width', 1200)}x{canvas.get('height', 630)} pixels.",
                f"Background: {canvas.get('background_color', '#FFFFFF')}.",
                "CRITICAL LAYOUT RULES — you MUST obey these unconditionally:",
                "1. Preserve the exact X/Y position and bounding box of EVERY element from the reference.",
                "2. Do not move, resize, add, or remove any element.",
                "3. The spatial composition is FIXED — treat it as an immovable constraint.",
                "Within those constraints you are free to: improve colours, lighting, shadows, gradients, "
                "textures, image realism, and overall visual polish. Rewrite text only when a user "
                "creative direction explicitly asks for new copy.",
            ]
        else:
            # Manual mode: strict layout preservation
            parts = [
                "You are a professional banner designer. I'm providing a reference layout image "
                "of a banner. Generate a polished, production-ready version of this banner.",
                f"Canvas: {canvas.get('width', 1200)}x{canvas.get('height', 630)} pixels.",
                f"Background: {canvas.get('background_color', '#FFFFFF')}.",
                "Preserve the exact layout, text positions, and relative sizing from the reference. "
                "Use the text EXACTLY as provided — do not change any words.",
                "Improve only the visual quality: add subtle shadows, gradients, refined typography, "
                "and professional polish while keeping all content identical.",
            ]

        for layer in layers:
            layer_type = layer.get("type", "")
            if layer_type == "text":
                content = layer.get("content", "")
                if content:
                    suffix = "keep this exact text." if mode == "manual" else "may be rewritten creatively."
                    parts.append(f'Text element: "{content}" — {suffix}')
            elif layer_type == "image":
                parts.append(
                    "Image area — maintain the exact position and size shown in the reference image."
                )

        if user_prompt:
            parts.append(f"Additional creative direction: {user_prompt}")

        parts.append(
            "Output a single image matching the exact dimensions. "
            "Do not add watermarks or borders."
        )

        return "\n".join(parts)

    async def close(self) -> None:
        """Clean up resources."""
        self._jobs.clear()
