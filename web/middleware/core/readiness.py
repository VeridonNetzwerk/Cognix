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
    <title>CogniX — wird initialisiert</title>
    <style>
      :root { color-scheme: dark; }
      * { margin: 0; padding: 0; box-sizing: border-box; }
      body {
        min-height: 100vh; display: flex; align-items: center;
        justify-content: center;
        background: #000000;
        color: #e8eaf2;
        font-family: -apple-system, 'SF Pro Display', 'Space Grotesk', system-ui, sans-serif;
        overflow: hidden;
        -webkit-font-smoothing: antialiased;
      }
      .container {
        text-align: center;
        animation: fadeIn 0.6s ease-out;
      }
      @keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }
      .logo {
        width: 56px; height: 56px; margin: 0 auto 1.8rem;
        border-radius: 14px;
        background: linear-gradient(135deg, #7c5cff, #5b8def);
        display: flex; align-items: center; justify-content: center;
        box-shadow: 0 8px 32px rgba(124, 92, 255, 0.35);
        animation: pulseLogo 2s ease-in-out infinite;
      }
      @keyframes pulseLogo {
        0%, 100% { transform: scale(1); box-shadow: 0 8px 32px rgba(124, 92, 255, 0.35); }
        50% { transform: scale(1.05); box-shadow: 0 12px 40px rgba(124, 92, 255, 0.5); }
      }
      .logo svg { width: 30px; height: 30px; fill: white; }
      h1 {
        font-size: 1.05rem; font-weight: 500; margin: 0 0 0.3rem;
        letter-spacing: -0.01em;
      }
      .status {
        font-size: 0.8rem; color: #6e7080; margin: 0 0 1.8rem;
        min-height: 1.1em;
      }
      .progress-track {
        width: 240px; height: 4px; margin: 0 auto;
        background: rgba(255, 255, 255, 0.08);
        border-radius: 999px; overflow: hidden;
      }
      .progress-bar {
        height: 100%; width: 0%;
        background: linear-gradient(90deg, #7c5cff, #5b8def);
        border-radius: 999px;
        animation: progress 2.2s ease-in-out infinite;
      }
      @keyframes progress {
        0% { width: 0%; opacity: 0.6; }
        50% { width: 70%; opacity: 1; }
        100% { width: 100%; opacity: 0.6; }
      }
      .skip-btn {
        position: fixed; bottom: 24px; right: 28px;
        background: rgba(255, 255, 255, 0.06);
        border: 1px solid rgba(255, 255, 255, 0.1);
        color: #6e7080;
        padding: 0.5rem 1.1rem; border-radius: 999px;
        font-size: 0.8rem; font-weight: 500;
        cursor: pointer; transition: all 0.2s ease;
        font-family: inherit;
        display: flex; align-items: center; gap: 0.4rem;
      }
      .skip-btn:hover {
        background: rgba(255, 255, 255, 0.1);
        color: #e8eaf2;
        border-color: rgba(255, 255, 255, 0.2);
      }
      .skip-btn:active { transform: scale(0.97); }
    </style>
  </head>
  <body>
    <div class="container">
      <div class="logo">
        <svg viewBox="0 0 24 24"><path d="M12 2L2 19h20L12 2zm0 4.5L18.5 17h-13L12 6.5z"/></svg>
      </div>
      <h1>CogniX</h1>
      <p class="status" id="status">System wird initialisiert…</p>
      <div class="progress-track">
        <div class="progress-bar"></div>
      </div>
    </div>
    <button class="skip-btn" onclick="document.cookie='cognix_skip_loading=1; path=/; max-age=60'; window.location.reload();">
      Überspringen
      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14M13 6l6 6-6 6"/></svg>
    </button>
    <script>
      (async () => {
        const statusEl = document.getElementById('status');
        const stages = ['System wird initialisiert…', 'Datenbank wird vorbereitet…', 'Module werden geladen…', 'Fast fertig…'];
        let stage = 0;
        const interval = setInterval(() => {
          stage = Math.min(stage + 1, stages.length - 1);
          if (statusEl) statusEl.textContent = stages[stage];
        }, 700);
        async function check() {
          try {
            const r = await fetch('/api/v1/bot/status', { credentials: 'same-origin' });
            if (r.ok) { clearInterval(interval); window.location.reload(); }
          } catch (e) {}
        }
        check();
        setInterval(check, 1500);
      })();
    </script>
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

        if request.cookies.get("cognix_skip_loading") == "1":
            return await call_next(request)

        return HTMLResponse(_LOADING_HTML, status_code=200)
