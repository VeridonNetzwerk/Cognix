"""Readiness middleware — show a loading screen while the web panel boots.

Only applies to HTML page requests during the brief app-start window (before
the engine/IPC are initialized). API, static, auth and setup routes are always
allowed through so the panel can finish configuring and the bot can report
status. Once the app is ready, requests pass through untouched.
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import HTMLResponse

from web.app import APP_READY as _APP_READY
import web.app as _app_module


def _is_ready() -> bool:
    """Read the current readiness flag at request time (never cached)."""
    return bool(getattr(_app_module, "APP_READY", False))

# Routes that must never be intercepted by the loading screen.
_ALLOWED_PREFIXES = (
    "/api/",
    "/ws",
    "/health",
    "/static",
    "/docs",
    "/openapi.json",
    "/redoc",
    "/setup",
    "/login",
    "/logout",
    "/assets",
)

_LOADING_HTML = """<!doctype html>
<html lang="de">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <meta http-equiv="refresh" content="2" />
    <title>CogniX — wird initialisiert</title>
    <style>
      :root { color-scheme: dark; }
      body {
        margin: 0; min-height: 100vh; display: flex; align-items: center;
        justify-content: center; background: #0c0e1a; color: #e8eaf2;
        font-family: 'Space Grotesk', system-ui, -apple-system, sans-serif;
      }
      .card {
        text-align: center; padding: 2.5rem 3rem; border-radius: 1rem;
        background: #161a2b; border: 1px solid #2a3050;
        box-shadow: 0 10px 40px rgba(0,0,0,0.4);
      }
      .spinner {
        width: 42px; height: 42px; margin: 0 auto 1.25rem;
        border: 4px solid #2a3050; border-top-color: #7c5cff;
        border-radius: 50%; animation: spin 0.9s linear infinite;
      }
      @keyframes spin { to { transform: rotate(360deg); } }
      h1 { font-size: 1.15rem; margin: 0 0 0.4rem; font-weight: 600; }
      p { margin: 0; font-size: 0.85rem; color: #9aa0c0; }
    </style>
  </head>
  <body>
    <div class="card">
      <div class="spinner"></div>
      <h1>Web Panel wird initialisiert</h1>
      <p>CogniX startet — einen Moment bitte…</p>
    </div>
  </body>
</html>
"""


class ReadinessMiddleware(BaseHTTPMiddleware):
    """Serve the loading screen for HTML pages until the app is ready."""

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        path = request.url.path

        # Never intercept non-page traffic (API, websockets, static, auth…).
        if any(path.startswith(p) for p in _ALLOWED_PREFIXES):
            return await call_next(request)
        # Assets with a file extension are never HTML pages.
        if "." in path.split("?")[0].rsplit("/", 1)[-1]:
            return await call_next(request)
        # Only GET page loads are gated; everything else passes through.
        if request.method != "GET":
            return await call_next(request)

        if _is_ready():
            return await call_next(request)

        return HTMLResponse(_LOADING_HTML, status_code=200)
