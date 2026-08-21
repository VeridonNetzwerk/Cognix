"""Settings, 2FA, bot profile, and user appearance routes."""

from __future__ import annotations

import hashlib
import uuid as _uuid
from base64 import b64decode as _b64decode
from datetime import UTC, datetime as _dt2
from typing import Any

import discord
from fastapi import Cookie, Form, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select

from bot.config.logging import get_logger
from bot.runtime import get_bot
from bot.database.models.content.bot_profile import BotProfile
from bot.database.models.auth.web_user import BackupCode, WebRole, WebUser
from bot.database.models.auth.web_user_settings import (
    MODULES,
    WebUserModulePermission,
    WebUserSettings,
)
from bot.database.session import db_session
from web.deps import ACCESS_COOKIE
from bot.pages._shared import _render, _require_cog, _require_user, router
from web.security import totp as _totp
from web.security.permissions import get_permission_map, has_permission

log = get_logger("web.pages.settings")

_VALID_THEMES = ("dark", "light", "system")
_VALID_REFRESH_INTERVALS = (1, 5, 10, 30)
_VALID_ACTIVITY_TYPES = ("none", "playing", "listening", "watching", "competing", "streaming")
_VALID_STATUSES = ("online", "idle", "dnd", "invisible")

_ACTIVITY_TYPE_MAP = {
    "playing": discord.ActivityType.playing,
    "listening": discord.ActivityType.listening,
    "watching": discord.ActivityType.watching,
    "competing": discord.ActivityType.competing,
    "streaming": discord.ActivityType.streaming,
}

_STATUS_MAP = {
    "online": discord.Status.online,
    "idle": discord.Status.idle,
    "dnd": discord.Status.dnd,
    "invisible": discord.Status.invisible,
}


def _get_bot_guilds() -> list[dict[str, Any]]:
    """Return list of guilds the bot is in, with name and icon."""
    bot = get_bot()
    if bot is None:
        return []
    return [
        {
            "id": str(g.id),
            "name": g.name,
            "icon_url": str(g.icon.url) if g.icon else None,
            "member_count": g.member_count or 0,
        }
        for g in bot.guilds
    ]


async def _get_or_create_settings(session, user) -> WebUserSettings:
    row = await session.get(WebUserSettings, user.id)
    if row is None:
        row = WebUserSettings(user_id=user.id, updated_at=_dt2.now(tz=UTC))
        session.add(row)
    return row


async def _delete_backup_codes(session, user_id: _uuid.UUID) -> None:
    """Delete all existing backup codes for a user."""
    existing = (
        await session.scalars(select(BackupCode).where(BackupCode.user_id == user_id))
    ).all()
    for old in existing:
        await session.delete(old)


@router.get("/settings", response_class=HTMLResponse)
async def settings_view(
    request: Request,
    access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE),
) -> HTMLResponse:
    user = await _require_user(access_token)
    async with db_session() as s:
        settings = await _get_or_create_settings(s, user)
        all_users = []
        if user.role == WebRole.ADMIN:
            all_users = (await s.scalars(select(WebUser).order_by(WebUser.username))).all()
            user_perms = {}
            for u in all_users:
                user_perms[str(u.id)] = await get_permission_map(s, u)
        else:
            user_perms = {str(user.id): await get_permission_map(s, user)}
    return _render(
        request,
        "settings/settings.html",
        user=user,
        settings=settings,
        modules=MODULES,
        levels=["none", "read", "write"],
        all_users=all_users,
        user_perms=user_perms,
    )


@router.post("/settings/appearance")
async def settings_appearance(
    request: Request,
    theme: str = Form("system"),
    accent_color: str = Form("#60A5FA"),
    compact_mode: str = Form(""),
    reduce_motion: str = Form(""),
    refresh_interval: str = Form("5"),
    notifications_enabled: str = Form(""),
    sidebar_collapsed: str = Form(""),
    access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE),
) -> Response:
    user = await _require_user(access_token)
    if theme not in _VALID_THEMES:
        theme = "system"
    try:
        ri = int(refresh_interval)
    except (ValueError, TypeError):
        ri = 5
    if ri not in _VALID_REFRESH_INTERVALS:
        ri = 5
    async with db_session() as s:
        row = await _get_or_create_settings(s, user)
        row.theme = theme
        row.accent_color = accent_color[:16]
        row.font_size = "medium"  # kept for backward compat, no longer used
        extras = dict(row.extras or {})
        extras["compact_mode"] = compact_mode == "on"
        extras["reduce_motion"] = reduce_motion == "on"
        extras["refresh_interval"] = ri
        extras["notifications_enabled"] = notifications_enabled == "on"
        extras["sidebar_collapsed"] = sidebar_collapsed == "on"
        row.extras = extras
        row.updated_at = _dt2.now(tz=UTC)
    return RedirectResponse("/settings", status_code=303)


@router.post("/settings/2fa/enable")
async def settings_2fa_enable(
    request: Request,
    access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE),
) -> HTMLResponse:
    user = await _require_user(access_token)
    if user.totp_enabled:
        return RedirectResponse("/settings", status_code=303)
    secret = _totp.generate_secret()
    uri = _totp.provisioning_uri(secret, account=user.email or user.username)
    qr_url = _totp.qr_data_url(uri)
    async with db_session() as s:
        target = await s.get(WebUser, user.id)
        target.totp_secret_encrypted = _totp.encrypted_secret(secret)
    return _render(
        request,
        "settings/settings_2fa_setup.html",
        user=user,
        secret=secret,
        qr_url=qr_url,
    )


@router.post("/settings/2fa/verify")
async def settings_2fa_verify(
    request: Request,
    code: str = Form(...),
    access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE),
) -> Response:
    user = await _require_user(access_token)
    async with db_session() as s:
        target = await s.get(WebUser, user.id)
        if not target.totp_secret_encrypted:
            raise HTTPException(400, "no pending TOTP setup")
        secret = _totp.decrypt(target.totp_secret_encrypted)
        if not _totp.verify(secret, code):
            raise HTTPException(400, "invalid code")
        target.totp_enabled = True
        await _delete_backup_codes(s, user.id)
        codes = _totp.generate_backup_codes(8)
        for raw in codes:
            s.add(BackupCode(user_id=user.id, code_hash=hashlib.sha256(raw.encode()).hexdigest()))
    return _render(request, "settings/settings_2fa_codes.html", user=user, codes=codes)


@router.post("/settings/2fa/disable")
async def settings_2fa_disable(
    password: str = Form(...),
    code: str = Form(...),
    access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE),
) -> Response:
    user = await _require_user(access_token)
    from web.security.passwords import verify_password
    if not verify_password(password, user.password_hash):
        raise HTTPException(400, "invalid password")
    if not user.totp_enabled or not _totp.verify(_totp.decrypt(user.totp_secret_encrypted), code):
        raise HTTPException(400, "invalid code")
    async with db_session() as s:
        target = await s.get(WebUser, user.id)
        target.totp_enabled = False
        target.totp_secret_encrypted = ""
        await _delete_backup_codes(s, user.id)
    return RedirectResponse("/settings", status_code=303)


@router.post("/settings/permissions/{user_id}")
async def settings_permissions_update(
    user_id: str,
    request: Request,
    access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE),
) -> Response:
    me = await _require_user(access_token)
    if me.role != WebRole.ADMIN:
        raise HTTPException(403, "admin only")
    form = await request.form()
    target_id = _uuid.UUID(user_id)
    async with db_session() as s:
        target = await s.get(WebUser, target_id)
        if target is None:
            raise HTTPException(404, "user not found")
        if target.username == "admin":
            raise HTTPException(403, "admin account is locked")
        existing = {
            r.module: r
            for r in (
                await s.scalars(
                    select(WebUserModulePermission).where(
                        WebUserModulePermission.user_id == target_id
                    )
                )
            ).all()
        }
        for mod in MODULES:
            level = str(form.get(f"perm_{mod}", "read")).lower()
            if level not in ("none", "read", "write"):
                level = "read"
            row = existing.get(mod)
            if row is None:
                s.add(WebUserModulePermission(user_id=target_id, module=mod, level=level))
            else:
                row.level = level
    return RedirectResponse("/settings", status_code=303)


# -------------------- /bot-profile --------------------------------------

@router.get("/bot-profile", response_class=HTMLResponse)
async def bot_profile_view(
    request: Request,
    access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE),
) -> HTMLResponse:
    user = await _require_user(access_token)
    _require_cog("cogs.bot_profile.bot_profile")
    async with db_session() as s:
        if not await has_permission(s, user, "bot_profile", level="read"):
            raise HTTPException(403, "forbidden")
        prof = await s.get(BotProfile, 1)
        if prof is None:
            prof = BotProfile(id=1, updated_at=_dt2.now(tz=UTC))
            s.add(prof)
            await s.flush()
    return _render(request, "settings/bot_profile.html", user=user, profile=prof, guilds=_get_bot_guilds())


@router.post("/bot-profile")
async def bot_profile_save(
    request: Request,
    display_name: str = Form(""),
    about_me: str = Form(""),
    avatar_data: str = Form(""),
    banner_data: str = Form(""),
    activity_type: str = Form("playing"),
    activity_text: str = Form(""),
    status: str = Form("online"),
    access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE),
) -> Response:
    user = await _require_user(access_token)
    _require_cog("cogs.bot_profile.bot_profile")
    async with db_session() as s:
        if not await has_permission(s, user, "bot_profile", level="write"):
            raise HTTPException(403, "forbidden")
        prof = await s.get(BotProfile, 1)
        if prof is None:
            prof = BotProfile(id=1, updated_at=_dt2.now(tz=UTC))
            s.add(prof)
        prof.display_name = display_name[:64]
        prof.about_me = about_me[:512]
        if avatar_data.startswith("data:"):
            prof.avatar_data = avatar_data[:1_000_000]
        if banner_data.startswith("data:"):
            prof.banner_data = banner_data[:2_000_000]
        prof.activity_type = activity_type if activity_type in _VALID_ACTIVITY_TYPES else "none"
        prof.activity_text = activity_text[:128]
        prof.status = status if status in _VALID_STATUSES else "online"
        prof.updated_at = _dt2.now(tz=UTC)

    bot = get_bot()
    if bot is None or bot.user is None:
        return RedirectResponse("/bot-profile", status_code=303)

    try:
        kwargs: dict[str, Any] = {}
        if display_name and display_name != bot.user.name:
            kwargs["username"] = display_name
        if avatar_data.startswith("data:image"):
            try:
                kwargs["avatar"] = _b64decode(avatar_data.split(",", 1)[1])
            except (IndexError, ValueError):
                log.warning("avatar_decode_failed", exc_info=True)
        if banner_data.startswith("data:image"):
            try:
                kwargs["banner"] = _b64decode(banner_data.split(",", 1)[1])
            except (IndexError, ValueError):
                log.warning("banner_decode_failed", exc_info=True)
        if kwargs:
            try:
                await bot.user.edit(**kwargs)
            except discord.HTTPException:
                log.warning("bot_profile_edit_failed", exc_info=True)
        activity = None
        if activity_type != "none":
            activity = discord.Activity(
                type=_ACTIVITY_TYPE_MAP.get(activity_type, discord.ActivityType.playing),
                name=activity_text or "Cognix",
            )
        await bot.change_presence(
            activity=activity,
            status=_STATUS_MAP.get(status, discord.Status.online),
        )
    except discord.HTTPException:
        log.warning("bot_presence_update_failed", exc_info=True)
    return RedirectResponse("/bot-profile", status_code=303)
