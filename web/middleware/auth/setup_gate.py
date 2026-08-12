"""Block all routes until first-run setup is complete.

Allow-list: setup endpoints, health checks, and static frontend assets.
"""

from __future__ import annotations

import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from sqlalchemy import select

from bot.database.models.system.system_config import SystemConfig
from bot.database.session import db_session

ALLOWED_PREFIXES = (
    "/api/v1/setup",
    "/api/v1/auth/health",
    "/health",
    "/docs",
    "/openapi.json",
    "/redoc",
    "/api/docs",
    "/api/openapi.json",
    "/setup",
    "/login",
    "/logout",
    "/static",
    "/assets",
)


class SetupGateMiddleware(BaseHTTPMiddleware):
    """Returns 423 when system is not configured yet (except setup endpoints)."""

    # Cache key: process start time (monotonic) so it invalidates on restart.
    _cache: tuple[bool, float] = (False, 0.0)
    _CACHE_TTL = 5.0  # seconds

    @classmethod
    def _is_configured_cached(cls) -> bool:
        now = time.monotonic()
        configured, ts = cls._cache
        if configured and (now - ts) < cls._CACHE_TTL:
            return True
        return False

    @classmethod
    def invalidate(cls) -> None:
        cls._cache = (False, 0.0)

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        path = request.url.path
        # Frontend pages (HTML) are allowed; the SPA itself routes to /setup.
        if path == "/" or path.startswith(ALLOWED_PREFIXES):
            return await call_next(request)

        configured = self._is_configured_cached()
        if not configured:
            async with db_session() as session:
                row = await session.scalar(select(SystemConfig).where(SystemConfig.id == 1))
                configured = bool(row and row.configured)
                # Update cache only on positive result (avoid caching False permanently)
                if configured:
                    self._cache = (True, time.monotonic())

        if not configured:
            if path.startswith("/api/"):
                return JSONResponse(
                    {"error": "setup_required", "detail": "First-run setup is required."},
                    status_code=423,
                )
            # HTML routes: redirect everything to /setup until configured.
            from starlette.responses import RedirectResponse
            return RedirectResponse("/setup", status_code=303)

        return await call_next(request)
