"""Server-side in-memory session middleware.

Replaces Starlette's cookie-based SessionMiddleware. The cookie only
stores a session ID; all data lives in a server-side dict. This avoids
cookie size limits and race conditions where overlapping requests read
stale cookie data.
"""

from __future__ import annotations

import uuid
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# Global in-memory session store: session_id -> data dict
_store: dict[str, dict[str, Any]] = {}

COOKIE_NAME = "banner_sid"
MAX_AGE = 14 * 24 * 60 * 60  # 14 days


class ServerSessionMiddleware(BaseHTTPMiddleware):
    """Middleware that stores session data server-side in memory."""

    async def dispatch(self, request: Request, call_next) -> Response:
        # Read session ID from cookie
        sid = request.cookies.get(COOKIE_NAME)
        if sid is None or sid not in _store:
            sid = str(uuid.uuid4())
            _store[sid] = {}

        # Attach session data to request.state so it's accessible
        # via request.session (we monkey-patch the scope)
        request.scope["session"] = _store[sid]

        response = await call_next(request)

        # Set the session ID cookie
        response.set_cookie(
            key=COOKIE_NAME,
            value=sid,
            max_age=MAX_AGE,
            httponly=True,
            samesite="lax",
        )

        return response
