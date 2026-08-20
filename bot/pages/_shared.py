"""Shared helpers for HTML view routes."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from jinja2 import ChoiceLoader, FileSystemLoader
from sqlalchemy import select

from bot.runtime import get_bot, get_bot_info
from bot.database.models.system.system_config import SystemConfig
from bot.database.models.auth.web_user import WebUser
from bot.database.session import db_session
from web.security.tokens import TokenError, decode_token

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
COGS_DIR = Path(__file__).resolve().parent.parent.parent / "cogs"


def _get_template_loaders() -> list[FileSystemLoader]:
    """Build list of template loaders: core templates + each cog's templates dir."""
    loaders = [FileSystemLoader(str(TEMPLATES_DIR))]
    if COGS_DIR.exists():
        for cog_subdir in sorted(COGS_DIR.iterdir()):
            if not cog_subdir.is_dir() or cog_subdir.name.startswith("_"):
                continue
            cog_templates = cog_subdir / "templates"
            if cog_templates.exists():
                loaders.append(FileSystemLoader(str(cog_templates)))
    return loaders


templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
# Override the loader with a ChoiceLoader that includes cog templates
templates.env.loader = ChoiceLoader(_get_template_loaders())

router = APIRouter(include_in_schema=False)


async def _current_user(access_token: str | None) -> WebUser | None:
    if not access_token:
        return None
    try:
        payload = decode_token(access_token, expected_type="access")
    except TokenError:
        return None
    try:
        user_id = uuid.UUID(payload["sub"])
    except (KeyError, ValueError):
        return None
    async with db_session() as s:
        user = await s.get(WebUser, user_id)
        if user is None or not user.is_active or user.deleted_at is not None:
            return None
        return user


async def _system_configured() -> bool:
    async with db_session() as s:
        row = await s.scalar(select(SystemConfig).where(SystemConfig.id == 1))
        return bool(row and row.configured)


def _render(request: Request, template: str, **ctx: Any) -> HTMLResponse:
    ctx.setdefault("user", None)
    ctx.setdefault("bot_info", get_bot_info())
    ctx.setdefault("user_settings", None)
    ctx.setdefault("loaded_cogs", _get_loaded_cogs_set())
    ctx.setdefault("cog_module_categories", _get_cog_module_categories())
    ctx.setdefault("cog_categories", _get_cog_categories())
    ctx.setdefault("servers", _get_servers())
    ctx.setdefault("selected_server_id", _get_selected_server_id(request))
    return templates.TemplateResponse(request, template, ctx)


_sync_engine = None
_sync_engine_url = None


def _get_sync_engine():
    global _sync_engine, _sync_engine_url
    from sqlalchemy import create_engine as _create_engine
    from bot.config.settings import get_settings

    settings = get_settings()
    db_url = settings.database_url
    if db_url.startswith("sqlite+aiosqlite"):
        sync_url = db_url.replace("sqlite+aiosqlite", "sqlite")
    elif db_url.startswith("postgresql+asyncpg"):
        sync_url = db_url.replace("postgresql+asyncpg", "postgresql+psycopg2")
    else:
        sync_url = db_url

    if _sync_engine is None or _sync_engine_url != sync_url:
        _sync_engine = _create_engine(sync_url, echo=False, future=True, pool_pre_ping=True)
        _sync_engine_url = sync_url
    return _sync_engine


def _get_servers() -> list:
    """Return all active servers for the header selector (sync query)."""
    from bot.database.models.server.server import Server

    engine = _get_sync_engine()
    with engine.connect() as conn:
        result = conn.execute(select(Server).where(Server.is_active.is_(True)).order_by(Server.name))
        return list(result.scalars().all())


def _get_selected_server_id(request: Request) -> int | None:
    """Read the selected server ID from cookie."""
    raw = request.cookies.get("selected_server_id")
    if raw:
        try:
            return int(raw)
        except ValueError:
            pass
    return None


def _get_cog_module_categories() -> dict[str, str]:
    """Map cog module names to their COG_INFO category."""
    from bot.cogs.registry import get_all_cog_info
    return {ci["module"]: ci.get("category", "") for ci in get_all_cog_info()}


def _get_cog_categories() -> dict[str, dict[str, str]]:
    """Return COG_CATEGORIES for nav group headers."""
    from bot.cogs.registry import COG_CATEGORIES
    return COG_CATEGORIES


def _get_loaded_cogs_set() -> set[str]:
    """Return the set of all loaded cog module names (registry + bot.extensions)."""
    from bot.cogs.registry import get_loaded_cogs
    loaded = set(get_loaded_cogs())
    bot = get_bot()
    if bot is not None:
        loaded |= set(bot.extensions.keys())
    return loaded


def _require_cog(cog_module: str) -> None:
    loaded = _get_loaded_cogs_set()
    if cog_module == "__any__":
        if not loaded:
            raise HTTPException(404, "No cogs loaded. Install and load a cog first.")
    elif cog_module not in loaded:
        raise HTTPException(404, f"This feature requires the '{cog_module.split('.')[-1].title()}' cog to be loaded.")


async def _require_user(access_token: str | None) -> WebUser:
    user = await _current_user(access_token)
    if user is None:
        raise HTTPException(status.HTTP_307_TEMPORARY_REDIRECT,
                            headers={"Location": "/login"})
    return user
