"""Gemini API integration for AI-powered banner recommendations."""

from __future__ import annotations

import json
import logging
from typing import Any

import google.generativeai as genai

logger = logging.getLogger(__name__)


class GeminiService:
    """Wraps the Google Gemini generative-AI API to produce creative
    recommendations for banner projects."""

    def __init__(self, api_key: str) -> None:
        genai.configure(api_key=api_key)
        self._model = genai.GenerativeModel("gemini-pro")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def generate_ui_data(self, user_profile: dict) -> dict:
        """Call Gemini to obtain personalised banner recommendations.

        Args:
            user_profile: Contextual information about the user/project such as
                industry, target audience, brand colours, etc.

        Returns:
            A dict with keys ``recommended_templates``, ``copy_suggestions``,
            ``color_palette``, and ``layout_tips``.
        """
        prompt = self._build_prompt(user_profile)

        try:
            response = await self._model.generate_content_async(prompt)
            return self._parse_response(response)
        except Exception:
            logger.exception("Gemini API call failed")
            return {
                "recommended_templates": [],
                "copy_suggestions": [],
                "color_palette": [],
                "layout_tips": [],
            }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_prompt(user_profile: dict) -> str:
        """Construct the Gemini prompt from the user profile."""
        profile_json = json.dumps(user_profile, ensure_ascii=False, indent=2)
        return (
            "You are a professional graphic-design assistant for an online banner "
            "creation tool. Based on the following user profile, provide creative "
            "recommendations in **valid JSON** (no markdown fences) with these keys:\n"
            "  - recommended_templates: list of template IDs or style names\n"
            "  - copy_suggestions: list of headline / tagline suggestions\n"
            "  - color_palette: list of hex colour codes that suit the brand\n"
            "  - layout_tips: list of short actionable layout tips\n\n"
            f"User profile:\n{profile_json}\n\n"
            "Respond ONLY with the JSON object."
        )

    @staticmethod
    def _parse_response(response: Any) -> dict:
        """Extract and validate JSON from the Gemini response text."""
        text: str = response.text.strip()

        # Strip optional markdown code fences
        if text.startswith("```"):
            first_newline = text.index("\n")
            text = text[first_newline + 1 :]
        if text.endswith("```"):
            text = text[: text.rfind("```")]

        text = text.strip()

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            logger.error("Failed to parse Gemini response as JSON: %s", text[:200])
            return {
                "recommended_templates": [],
                "copy_suggestions": [],
                "color_palette": [],
                "layout_tips": [],
            }

        # Ensure all expected keys are present
        defaults: dict[str, list] = {
            "recommended_templates": [],
            "copy_suggestions": [],
            "color_palette": [],
            "layout_tips": [],
        }
        for key, default in defaults.items():
            data.setdefault(key, default)

        return data
