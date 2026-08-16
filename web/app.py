"""FastAPI application factory.

The dashboard is server-rendered (Jinja2) and lives at ``/`` — no separate
Node build step is required. JSON API stays under ``/api/v1``.
"""

from __future__ import annotations

import traceback
from contextlib import asynccontextmanager

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from bot.runtime import get_bot_info
from bot.config.constants import API_V1_PREFIX
from bot.config.logging import configure_logging, get_logger
from bot.config.settings import get_settings
from bot.database import init_engine
from bot.database.session import dispose_engine
from web.middleware.auth import AuthRefreshMiddleware, SetupGateMiddleware
from web.middleware.core import RateLimitMiddleware, RequestIDMiddleware
from web.api import auth as auth_api
from web.api import bot as bot_api
from web.api import servers as servers_api
from web.api import users as users_api
from web.api import moderation as moderation_api
from web.api import settings as settings_api
from web.api import content as content_api
from web.api import ws as ws_api
from bot.pages import router as views_router
from bot.pages._shared import templates
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
        from bot.database.seed_embeds import seed_default_embed_templates
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
        auth_api.auth_router,
        auth_api.setup_router,
        bot_api.bot_control_router,
        bot_api.cogs_router,
        bot_api.dashboard_router,
        servers_api.servers_router,
        servers_api.stats_router,
        users_api.users_router,
        users_api.web_users_router,
        moderation_api.moderation_router,
        moderation_api.tickets_router,
        moderation_api.backups_router,
        settings_api.settings_router,
        settings_api.audit_router,
        content_api.embed_templates_router,
        content_api.music_panel_router,
        ws_api.ws_router,
    ):
        app.include_router(r, prefix=API_V1_PREFIX)

    # ---- Static files (logo, favicon, etc.) ----
    static_dir = Path(__file__).resolve().parent.parent / "bot" / "static"
    if static_dir.is_dir():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    # ---- HTML dashboard (Jinja2) — primary user-facing surface ----
    app.include_router(views_router)

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
            {"user": None, "bot_info": get_bot_info(), "status": exc.status_code,
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
            {"user": None, "bot_info": get_bot_info(), "status": 500, "title": "Internal error",
             "detail": str(exc) if settings.is_dev else
                       "Something broke. Check the bot console for the traceback."},
            status_code=500,
        )

    return app


app = create_app()
