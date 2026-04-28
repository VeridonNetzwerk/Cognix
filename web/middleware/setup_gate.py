"""Block all routes until first-run setup is complete.

Allow-list: setup endpoints, health checks, and static frontend assets.
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from sqlalchemy import select

from database.models.system_config import SystemConfig
from database.session import db_session

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

    _cached_configured: bool = False

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        path = request.url.path
        # Frontend pages (HTML) are allowed; the SPA itself routes to /setup.
        if path == "/" or path.startswith(ALLOWED_PREFIXES):
            return await call_next(request)

        if not self._cached_configured:
            async with db_session() as session:
                row = await session.scalar(select(SystemConfig).where(SystemConfig.id == 1))
                configured = bool(row and row.configured)
            if not configured:
                if path.startswith("/api/"):
                    return JSONResponse(
                        {"error": "setup_required", "detail": "First-run setup is required."},
                        status_code=423,
                    )
                # HTML routes: redirect everything to /setup until configured.
                from starlette.responses import RedirectResponse
                return RedirectResponse("/setup", status_code=303)
            type(self)._cached_configured = True

        return await call_next(request)

    @classmethod
    def invalidate(cls) -> None:
        cls._cached_configured = False
