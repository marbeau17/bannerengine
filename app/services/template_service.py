"""Template management service for loading, caching, and querying banner templates."""

from __future__ import annotations

import os
from typing import Optional

from app.core.xml_parser import XMLTemplateParser
from app.models.template import BannerTemplate

# Mapping from directory/category key to Japanese display name.
CATEGORY_DISPLAY_NAMES: dict[str, str] = {
    "used_car": "中古自動車",
    "dressing": "ドレッシング",
    "stationery": "文房具",
    "apparel": "アパレル",
    "animal_funding": "動物支援ファンディング",
    "ramen": "ラーメン屋",
}


class TemplateService:
    """Service for loading, caching, and querying banner templates."""

    def __init__(self) -> None:
        self._parser = XMLTemplateParser()
        self._templates: dict[str, BannerTemplate] = {}

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def load_templates_from_directory(self, base_dir: str) -> None:
        """Recursively scan *base_dir*/xml_templates/ for .xml files and parse them.

        Each successfully parsed template is stored in the internal cache
        keyed by its ``pattern_id``.

        Args:
            base_dir: Project root directory that contains an ``xml_templates/``
                      subdirectory.
        """
        templates_dir = os.path.join(base_dir, "xml_templates")
        if not os.path.isdir(templates_dir):
            return

        for dirpath, _dirnames, filenames in os.walk(templates_dir):
            for filename in filenames:
                if not filename.lower().endswith(".xml"):
                    continue
                file_path = os.path.join(dirpath, filename)
                try:
                    templates = self._parser.parse_file(file_path)
                    for template in templates:
                        self._templates[template.meta.pattern_id] = template
                except Exception:
                    # Skip files that cannot be parsed so one bad file
                    # does not prevent the rest from loading.
                    continue

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    def get_categories(self) -> list[dict]:
        """Return a list of categories with template counts.

        Each entry is a dict with keys ``key``, ``display_name``, and ``count``.
        """
        counts: dict[str, int] = {}
        for template in self._templates.values():
            cat = template.meta.category
            counts[cat] = counts.get(cat, 0) + 1

        result: list[dict] = []
        for key, count in sorted(counts.items()):
            result.append(
                {
                    "key": key,
                    "display_name": CATEGORY_DISPLAY_NAMES.get(key, key),
                    "count": count,
                }
            )
        return result

    def get_templates_by_category(self, category: str) -> list[BannerTemplate]:
        """Return all templates that belong to *category*."""
        return [
            t for t in self._templates.values() if t.meta.category == category
        ]

    def get_template(self, pattern_id: str) -> BannerTemplate:
        """Return a single template by its *pattern_id*.

        Raises:
            KeyError: If the template is not found.
        """
        try:
            return self._templates[pattern_id]
        except KeyError:
            from app.core.exceptions import TemplateNotFoundError

            raise TemplateNotFoundError(pattern_id)

    def get_all_templates(self) -> list[BannerTemplate]:
        """Return every loaded template."""
        return list(self._templates.values())

    # Alias used by routers
    list_templates = get_all_templates

    def search_templates(self, query: str) -> list[BannerTemplate]:
        """Search templates by matching *query* against pattern_name, category,
        recommended_use, and layout_type (case-insensitive substring match).
        """
        query_lower = query.lower()
        results: list[BannerTemplate] = []
        for template in self._templates.values():
            meta = template.meta
            searchable = " ".join(
                [
                    meta.pattern_name,
                    meta.category,
                    meta.recommended_use,
                    meta.layout_type,
                    CATEGORY_DISPLAY_NAMES.get(meta.category, ""),
                ]
            ).lower()
            if query_lower in searchable:
                results.append(template)
        return results
