"""Banner generation orchestrator.

Coordinates template lookup, render instruction assembly, and
submission to the Nano Banana Pro rendering service.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.models.banner import GenerateResponse, RenderInstruction

if TYPE_CHECKING:
    from app.models.template import BannerTemplate, Slot


class BannerService:
    """Builds render instructions from templates and slot values, then
    submits them to Nano Banana Pro for image generation."""

    def __init__(self, template_service, nano_banana_client) -> None:
        self.template_service = template_service
        self.nano_banana_client = nano_banana_client

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def create_render_instruction(
        self,
        pattern_id: str,
        slot_values: dict,
        format: str = "png",
        quality: int = 95,
        dpi: int = 144,
    ) -> RenderInstruction:
        """Build a complete :class:`RenderInstruction` for a given template
        and set of slot values.

        Args:
            pattern_id: The ``pattern_id`` that identifies the template.
            slot_values: Mapping of ``slot_id`` -> value dict supplied by the
                user for each editable slot.
            format: Output image format (``png``, ``jpg``, ``webp``).
            quality: JPEG/WebP quality 1-100.
            dpi: Dots-per-inch for the output image.

        Returns:
            A fully-populated :class:`RenderInstruction` ready for submission.
        """
        template: BannerTemplate = self.template_service.get_template(pattern_id)

        canvas = {
            "width": template.meta.width,
            "height": template.meta.height,
            "background_color": template.design.background_value or "#FFFFFF",
            "format": format,
            "quality": quality,
            "dpi": dpi,
        }

        layers: list[dict] = []
        z_index = 0

        for slot in template.slots:
            value = slot_values.get(slot.id)
            if value is None and not slot.required:
                continue

            slot_layers = self._slot_to_layers(slot, value or {}, template)
            for layer in slot_layers:
                layer["z_index"] = z_index
                z_index += 1
                layers.append(layer)

        return RenderInstruction(
            schema_version="1.0",
            canvas=canvas,
            layers=layers,
        )

    async def submit_generation(self, render_instruction: RenderInstruction) -> str:
        """Submit a :class:`RenderInstruction` to Nano Banana Pro.

        Returns:
            The ``job_id`` assigned by the rendering service.
        """
        job_id: str = await self.nano_banana_client.submit_render(
            render_instruction.model_dump()
        )
        return job_id

    async def check_progress(self, job_id: str) -> GenerateResponse:
        """Poll Nano Banana Pro for the current status of a rendering job.

        Returns:
            A :class:`GenerateResponse` reflecting the latest job state.
        """
        status_data: dict = await self.nano_banana_client.get_status(job_id)

        return GenerateResponse(
            job_id=job_id,
            status=status_data.get("status", "unknown"),
            progress=status_data.get("progress", 0),
            file_url=status_data.get("file_url"),
            error=status_data.get("error"),
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _slot_to_layers(
        self, slot: "Slot", value: dict, template: "BannerTemplate"
    ) -> list[dict]:
        """Convert a single slot + its user-supplied value into one or more
        render layers.

        Percentage-based slot coordinates are converted to absolute pixels
        using the template canvas dimensions.
        """
        canvas_w = template.meta.width
        canvas_h = template.meta.height

        # Convert percentage coordinates to absolute pixels (session overrides take priority)
        sx = float(value.get("x", slot.x)) if isinstance(value, dict) and value.get("x") else slot.x
        sy = float(value.get("y", slot.y)) if isinstance(value, dict) and value.get("y") else slot.y
        sw = float(value.get("width", slot.width)) if isinstance(value, dict) and value.get("width") else slot.width
        sh = float(value.get("height", slot.height)) if isinstance(value, dict) and value.get("height") else slot.height
        abs_x = int(sx / 100.0 * canvas_w)
        abs_y = int(sy / 100.0 * canvas_h)
        abs_width = int(sw / 100.0 * canvas_w)
        abs_height = int(sh / 100.0 * canvas_h)

        position = {"x": abs_x, "y": abs_y}
        size = {"width": abs_width, "height": abs_height}

        slot_type = slot.type.value  # enum -> str

        if slot_type == "text":
            return self._text_layer(slot, value, position, size)
        elif slot_type == "image":
            return self._image_layer(slot, value, position, size)
        elif slot_type == "button":
            return self._button_layers(slot, value, position, size)
        elif slot_type == "image_or_text":
            # Delegate based on what the user actually supplied
            if value.get("source_url"):
                return self._image_layer(slot, value, position, size)
            return self._text_layer(slot, value, position, size)

        return []

    # -- Layer builders --------------------------------------------------

    @staticmethod
    def _text_layer(
        slot: "Slot", value: dict, position: dict, size: dict
    ) -> list[dict]:
        return [
            {
                "layer_id": f"text_{slot.id}",
                "type": "text",
                "position": position,
                "size": size,
                "content": value.get("content", ""),
                "font_family": value.get("font_family", "sans-serif"),
                "font_size": value.get("font_size", slot.font_size_guideline or "16px"),
                "font_weight": value.get("font_weight", slot.font_weight or "normal"),
                "color": value.get("color", slot.color or "#000000"),
            }
        ]

    @staticmethod
    def _image_layer(
        slot: "Slot", value: dict, position: dict, size: dict
    ) -> list[dict]:
        return [
            {
                "layer_id": f"image_{slot.id}",
                "type": "image",
                "position": position,
                "size": size,
                "source_url": value.get("source_url", ""),
                "fit": value.get("fit", "cover"),
                "opacity": value.get("opacity", 1.0),
                "prompt": value.get("prompt", ""),
                "generation_model": value.get("generation_model", "nano-bannara-pro-2"),
            }
        ]

    @staticmethod
    def _button_layers(
        slot: "Slot", value: dict, position: dict, size: dict
    ) -> list[dict]:
        """A button is rendered as a rectangle background layer plus a
        centered text layer on top."""
        bg_color = value.get("bg_color", slot.bg_color or "#000000")
        text_color = value.get("text_color", slot.text_color or "#FFFFFF")
        label = value.get("content", slot.default_label or "Click")

        rect_layer = {
            "layer_id": f"button_bg_{slot.id}",
            "type": "rect",
            "position": position,
            "size": size,
            "color": bg_color,
            "border_radius": value.get("border_radius", 4),
        }

        text_layer = {
            "layer_id": f"button_text_{slot.id}",
            "type": "text",
            "position": position,
            "size": size,
            "content": label,
            "font_family": value.get("font_family", "sans-serif"),
            "font_size": value.get("font_size", slot.font_size_guideline or "14px"),
            "font_weight": value.get("font_weight", slot.font_weight or "bold"),
            "color": text_color,
            "text_align": "center",
            "vertical_align": "middle",
        }

        return [rect_layer, text_layer]
