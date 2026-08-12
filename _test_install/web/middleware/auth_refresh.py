"""Auto-rotate access tokens using the refresh cookie.

When the access cookie is missing or expired but a valid refresh cookie
exists, this middleware mints a fresh access (+ refresh) pair, sets them
on the outgoing response, and rewrites the inbound ``cookie`` header so
downstream FastAPI dependencies see the new access token immediately.

This is what implements "Remember-Me" continuity for HTML pages — without
it, users get logged out as soon as the short-lived access JWT expires.
"""

from __future__ import annotations

from typing import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from config.logging import get_logger
from database.session import db_session
from web.deps import ACCESS_COOKIE, REFRESH_COOKIE
from web.routes.auth import _set_cookies
from web.security.tokens import TokenError, decode_token
from web.services.auth_service import AuthError, rotate_refresh

log = get_logger("web.auth_refresh")


def _access_alive(token: str | None) -> bool:
    if not token:
        return False
    try:
        decode_token(token, expected_type="access")
        return True
    except TokenError:
        return False


def _rewrite_cookie_header(request: Request, new_access: str) -> None:
    """Replace the ``cognix_access`` value in the inbound Cookie header so
    downstream dependencies (which read raw cookies via Starlette) pick up
    the fresh token within the same request."""
    headers = list(request.scope.get("headers") or [])
    cookie_pair = next(
        ((i, v.decode("latin-1")) for i, (k, v) in enumerate(headers) if k == b"cookie"),
        None,
    )
    parts: list[str] = []
    if cookie_pair is not None:
        idx, raw = cookie_pair
        for piece in raw.split(";"):
            piece = piece.strip()
            if not piece:
                continue
            name = piece.split("=", 1)[0].strip()
            if name == ACCESS_COOKIE:
                continue
            parts.append(piece)
    parts.append(f"{ACCESS_COOKIE}={new_access}")
    new_value = "; ".join(parts).encode("latin-1")
    if cookie_pair is not None:
        headers[cookie_pair[0]] = (b"cookie", new_value)
    else:
        headers.append((b"cookie", new_value))
    request.scope["headers"] = headers


class AuthRefreshMiddleware(BaseHTTPMiddleware):
    """Transparent access-token rotation using the long-lived refresh cookie."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        path = request.url.path

        # Only worry about authenticated UI/API surfaces. Skip auth endpoints
        # themselves and static health checks to avoid pointless DB hits.
        skip_prefixes = ("/auth/", "/api/v1/auth/", "/static/", "/health", "/login", "/setup", "/logout")
        if any(path.startswith(p) for p in skip_prefixes):
            return await call_next(request)

        access = request.cookies.get(ACCESS_COOKIE)
        refresh = request.cookies.get(REFRESH_COOKIE)

        new_pair: tuple[str, str, "object", bool] | None = None
        if not _access_alive(access) and refresh:
            try:
                async with db_session() as s:
                    new_access, new_refresh, exp, remember_me = await rotate_refresh(
                        s,
                        raw_token=refresh,
                        user_agent=request.headers.get("user-agent", "")[:256],
                        ip=request.client.host if request.client else "",
                    )
                new_pair = (new_access, new_refresh, exp, remember_me)
                _rewrite_cookie_header(request, new_access)
            except AuthError as exc:
                log.info("auth_refresh_failed", path=path, error=str(exc))
            except Exception as exc:  # noqa: BLE001
                log.warning("auth_refresh_error", path=path, error=str(exc))

        response = await call_next(request)

        if new_pair is not None:
            _set_cookies(response, new_pair[0], new_pair[1], new_pair[2], remember_me=new_pair[3])

        return response
