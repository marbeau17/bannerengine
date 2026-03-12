"""Preview management service for banner templates."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.core.exceptions import GenerationError, TemplateNotFoundError
from app.core.svg_renderer import SvgRenderer

if TYPE_CHECKING:
    from app.services.template_service import TemplateService


class PreviewService:
    """Generates SVG previews for banner templates."""

    def __init__(self, renderer: SvgRenderer, template_service: TemplateService) -> None:
        self._renderer = renderer
        self._template_service = template_service

    async def generate_preview(self, pattern_id: str, slot_values: dict[str, Any]) -> str:
        """Generate a full SVG preview with the supplied slot values.

        Parameters
        ----------
        pattern_id:
            The ``pattern_id`` that identifies the template.
        slot_values:
            Mapping of slot id -> value (string, dict, or SlotValue model).

        Returns
        -------
        str
            An SVG document string suitable for embedding in HTML.

        Raises
        ------
        TemplateNotFoundError
            If no template matches *pattern_id*.
        GenerationError
            If SVG rendering fails.
        """
        template = await self._resolve_template(pattern_id)
        svg_string = self._renderer.render(template, slot_values)
        return svg_string

    async def generate_thumbnail(self, pattern_id: str) -> str:
        """Generate a thumbnail SVG using default / empty slot values.

        This is intended for the template selection page where no user
        content has been supplied yet.

        Parameters
        ----------
        pattern_id:
            The ``pattern_id`` that identifies the template.

        Returns
        -------
        str
            An SVG document string with placeholder content.

        Raises
        ------
        TemplateNotFoundError
            If no template matches *pattern_id*.
        GenerationError
            If SVG rendering fails.
        """
        template = await self._resolve_template(pattern_id)

        # Build a default values dict using slot defaults where available.
        default_values: dict[str, Any] = {}
        for slot in template.slots:
            if slot.default_label:
                default_values[slot.id] = slot.default_label
            # All other slots will render as placeholders (empty value).

        svg_string = self._renderer.render(template, default_values)
        return svg_string

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _resolve_template(self, pattern_id: str):
        """Look up a template by *pattern_id* via the template service.

        Raises ``TemplateNotFoundError`` when not found.
        """
        template = await self._template_service.get_template(pattern_id)
        if template is None:
            raise TemplateNotFoundError(pattern_id)
        return template
