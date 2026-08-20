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
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>CogniX — Starting up</title>
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
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 0;
      }
      @keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }
      .text-logo {
        font-size: 3.5rem; font-weight: 800; margin: 0 0 1rem;
        letter-spacing: -0.03em;
        background: linear-gradient(135deg, #7c5cff, #5b8def);
        -webkit-background-clip: text;
        background-clip: text;
        -webkit-text-fill-color: transparent;
      }
      .status {
        font-size: 0.78rem; color: #6e7080; margin: 0 0 1.8rem;
        min-height: 1.1em;
        transition: opacity 0.3s ease;
      }
      .progress-track {
        width: 260px; height: 4px; margin: 0 auto;
        background: rgba(255, 255, 255, 0.08);
        border-radius: 999px; overflow: hidden;
        position: relative;
      }
      .progress-bar {
        height: 100%; width: 0%;
        background: linear-gradient(90deg, #7c5cff, #5b8def);
        border-radius: 999px;
        transition: width 0.5s ease;
      }
      .progress-bar::after {
        content: '';
        position: absolute; top: 0; left: 0; right: 0; bottom: 0;
        background: linear-gradient(90deg, transparent, rgba(255,255,255,0.15), transparent);
        animation: shimmer 1.5s ease-in-out infinite;
      }
      @keyframes shimmer {
        0% { transform: translateX(-100%); }
        100% { transform: translateX(100%); }
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
      <div class="text-logo">CogniX</div>
      <p class="status" id="status">Initializing…</p>
      <div class="progress-track">
        <div class="progress-bar" id="progressBar"></div>
      </div>
    </div>
    <button class="skip-btn" onclick="document.cookie='cognix_skip_loading=1; path=/; max-age=60'; window.location.reload();">
      Skip
      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14M13 6l6 6-6 6"/></svg>
    </button>
    <script>
      (async () => {
        const statusEl = document.getElementById('status');
        const barEl = document.getElementById('progressBar');
        const stages = [
          { label: 'Initializing…', pct: 10 },
          { label: 'Connecting to database…', pct: 30 },
          { label: 'Loading modules…', pct: 50 },
          { label: 'Syncing cog store…', pct: 70 },
          { label: 'Almost ready…', pct: 90 },
        ];
        let stage = 0;
        function setStage(i) {
          stage = Math.min(i, stages.length - 1);
          if (statusEl) statusEl.textContent = stages[stage].label;
          if (barEl) barEl.style.width = stages[stage].pct + '%';
        }
        setStage(0);
        const interval = setInterval(() => setStage(stage + 1), 800);
        async function check() {
          try {
            const r = await fetch('/api/v1/bot/status', { credentials: 'same-origin' });
            if (r.ok) {
              clearInterval(interval);
              setStage(stages.length - 1);
              if (barEl) barEl.style.width = '100%';
              setTimeout(() => window.location.reload(), 200);
            }
          } catch (e) {}
        }
        check();
        setInterval(check, 1000);
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
