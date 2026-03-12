"""Dependency injection for the Banner Engine application."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from fastapi import Request


def get_session(request: Request) -> dict[str, Any]:
    """Return session data from the request.

    Relies on SessionMiddleware being installed on the app.
    """
    return request.session


def get_template_service():
    """Return a TemplateService instance.

    Uses lazy import so the module only needs to exist when the
    dependency is actually resolved at request time.
    """
    from app.services.template_service import TemplateService  # noqa: WPS433

    return TemplateService()


@lru_cache()
def get_settings():
    """Return a cached Settings instance.

    Uses lazy import so the module only needs to exist when the
    dependency is actually resolved at request time.
    """
    from app.core.config import Settings  # noqa: WPS433

    return Settings()
