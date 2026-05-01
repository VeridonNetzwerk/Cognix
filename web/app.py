"""FastAPI application factory.

The dashboard is server-rendered (Jinja2) and lives at ``/`` — no separate
Node build step is required. JSON API stays under ``/api/v1``.
"""

from __future__ import annotations

import traceback
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from config.constants import API_V1_PREFIX
from config.logging import configure_logging, get_logger
from config.settings import get_settings
from database import init_engine
from database.session import dispose_engine
from web.middleware.auth_refresh import AuthRefreshMiddleware
from web.middleware.rate_limit import RateLimitMiddleware
from web.middleware.request_id import RequestIDMiddleware
from web.middleware.setup_gate import SetupGateMiddleware
from web.routes import (
    auth,
    audit,
    backups,
    bot_control,
    cogs,
    embed_templates,
    moderation,
    music_panel,
    servers,
    settings as settings_route,
    setup,
    stats,
    tickets,
    users,
    views,
    web_users,
    ws,
)
from web.routes.views import templates
from web.services.bot_ipc import get_ipc

log = get_logger("web.app")


@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: ARG001
    configure_logging()
    settings = get_settings()
    settings.ensure_data_dirs()
    try:
        init_engine()
    except Exception as exc:  # noqa: BLE001
        log.error("db_init_failed", error=str(exc))
        raise
    # Seed default embed templates so the dashboard isn't empty.
    try:
        from database.seed_embeds import seed_default_embed_templates
        inserted = await seed_default_embed_templates()
        if inserted:
            log.info("embed_templates_seeded", count=inserted)
    except Exception as exc:  # noqa: BLE001
        log.warning("embed_seed_failed", error=str(exc))
    ipc = get_ipc()
    try:
        await ipc.connect()
    except Exception as exc:  # noqa: BLE001
        # IPC is optional (Redis disabled) — never block API startup on it.
        log.warning("ipc_connect_failed", error=str(exc))
    log.info("api_started", env=settings.app_env, host=settings.app_host, port=settings.app_port)
    try:
        yield
    finally:
        try:
            await ipc.close()
        except Exception:  # noqa: BLE001
            pass
        await dispose_engine()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="CogniX API",
        version="0.1.0",
        description="Modular Discord bot platform with secure web dashboard.",
        lifespan=lifespan,
        docs_url="/api/docs" if settings.is_dev else None,
        redoc_url=None,
        openapi_url="/api/openapi.json" if settings.is_dev else None,
    )

    # ---- Middleware (order matters: first added = outermost) ----
    app.add_middleware(RequestIDMiddleware)
    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(SetupGateMiddleware)
    app.add_middleware(AuthRefreshMiddleware)
    # Strip trailing slash so CORS origin matching works correctly.
    _origin = settings.app_base_url.rstrip("/")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[_origin, "http://localhost:25003", "http://localhost:3000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ---- Health ----
    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    # ---- API routers ----
    for r in (
        setup.router,
        auth.router,
        bot_control.router,
        cogs.router,
        servers.router,
        users.router,
        web_users.router,
        moderation.router,
        tickets.router,
        stats.router,
        backups.router,
        settings_route.router,
        audit.router,
        embed_templates.router,
        music_panel.router,
        ws.router,
    ):
        app.include_router(r, prefix=API_V1_PREFIX)

    # ---- HTML dashboard (Jinja2) — primary user-facing surface ----
    app.include_router(views.router)

    # ---- Error handlers ----
    @app.exception_handler(StarletteHTTPException)
    async def _http_exc(request: Request, exc: StarletteHTTPException):
        # Honour redirect-style HTTPException raised by view guards.
        if 300 <= exc.status_code < 400 and exc.headers and "Location" in exc.headers:
            return RedirectResponse(exc.headers["Location"], status_code=exc.status_code)
        if request.url.path.startswith("/api/"):
            return JSONResponse({"error": exc.detail}, status_code=exc.status_code)
        return templates.TemplateResponse(
            request, "error.html",
            {"user": None, "status": exc.status_code,
             "title": "Error" if exc.status_code != 404 else "Not found",
             "detail": str(exc.detail)},
            status_code=exc.status_code,
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):
        # Always log full traceback to console so the operator can debug.
        log.error(
            "unhandled_exception",
            path=request.url.path,
            method=request.method,
            error=f"{type(exc).__name__}: {exc}",
            traceback=traceback.format_exc(),
        )
        if request.url.path.startswith("/api/"):
            return JSONResponse(
                {"error": "internal_error",
                 "type": type(exc).__name__,
                 "detail": str(exc) if settings.is_dev else None},
                status_code=500,
            )
        return templates.TemplateResponse(
            request, "error.html",
            {"user": None, "status": 500, "title": "Internal error",
             "detail": str(exc) if settings.is_dev else
                       "Something broke. Check the bot console for the traceback."},
            status_code=500,
        )

    return app


app = create_app()
