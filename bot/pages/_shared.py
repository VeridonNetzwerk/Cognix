"""Shared helpers for HTML view routes."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select

from bot.runtime import get_bot, get_bot_info
from bot.database.models.system.system_config import SystemConfig
from bot.database.models.auth.web_user import WebUser
from bot.database.session import db_session
from web.security.tokens import TokenError, decode_token

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

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
    return templates.TemplateResponse(request, template, ctx)


def _get_loaded_cogs_set() -> set[str]:
    """Return the set of all loaded cog module names (registry + bot.extensions)."""
    from bot.cogs.registry import get_loaded_cogs
    loaded = set(get_loaded_cogs())
    bot = get_bot()
    if bot is not None:
        loaded |= set(bot.extensions.keys())
    return loaded


def _build_loaded_cog_list(live_cogs: set[str]) -> list[dict[str, Any]]:
    """Build a list of cog info dicts for all loaded cogs.

    Includes registry-known cogs and any extra loaded extensions.
    """
    from bot.cogs.registry import get_all_cog_info, _make_cog_info

    all_cogs = get_all_cog_info()
    loaded = [info for info in all_cogs if info["module"] in live_cogs]

    registry_modules = {info["module"] for info in all_cogs}
    for ext in live_cogs:
        if ext not in registry_modules:
            loaded.append(_make_cog_info(ext))

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
