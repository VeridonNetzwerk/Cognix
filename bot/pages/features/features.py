"""Members, embeds, welcome, invites, and misc API routes."""

from __future__ import annotations

import discord
from datetime import UTC, datetime as _dt2, timedelta as _td2
from typing import Any

from fastapi import Cookie, Form, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import desc, func, select

from bot.config.logging import get_logger
from bot.runtime import get_bot
from bot.database.models.auth.audit_log import AuditLog
from bot.database.models.auth.role_permission import RolePermission
from bot.database.models.auth.web_user import WebRole
from bot.database.models.auth.web_user_settings import WebUserSettings
from bot.database.models.content.embed_template import EmbedTemplate
from bot.database.models.invites.invite_stats import InviteStats
from bot.database.models.invites.invite_uses import InviteUse
from bot.database.models.server.server import Server
from bot.database.models.server.server_event_config import ServerEventConfig
from bot.database.session import db_session
from web.deps import ACCESS_COOKIE
from bot.pages._shared import _render, _require_cog, _require_user, _get_selected_server_id, router

log = get_logger("web.pages.features")


def _discord_obj(user_id: int) -> discord.Object:
    """Create a discord.Object for a user ID (used for bans etc.)."""
    return discord.Object(id=user_id)


def _hex_to_int(h: str, fallback: int) -> int:
    """Parse a hex color string, returning fallback on failure."""
    try:
        return int(h.lstrip("#"), 16)
    except ValueError:
        return fallback


def _form_bool(v: str) -> bool:
    """Interpret a form checkbox value as boolean."""
    return v.lower() in ("on", "true", "1", "yes")


def _form_channel_id(v: str) -> int | None:
    """Parse a channel ID string, returning None if empty/invalid."""
    return int(v) if v.strip().isdigit() else None


_DEFAULT_USER_SETTINGS: dict[str, Any] = {
    "theme": "system",
    "accent_color": "#60A5FA",
    "font_size": "medium",
    "compact_mode": False,
    "reduce_motion": False,
    "refresh_interval": 5,
    "notifications_enabled": True,
    "sidebar_collapsed": False,
}


def _get_guild_member(server_id: int, member_id: int) -> tuple[discord.Guild | None, discord.Member | None]:
    """Resolve a guild and member from the bot cache. Returns (None, None) if not found."""
    bot = get_bot()
    if bot is None:
        return None, None
    guild = bot.get_guild(server_id)
    if guild is None:
        return None, None
    return guild, guild.get_member(member_id)


# ---------- Embeds -----------------------------------------------------------

@router.get("/embeds", response_class=HTMLResponse)
async def embeds_view(request: Request,
                      access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE)) -> HTMLResponse:
    user = await _require_user(access_token)
    _require_cog("cogs.embeds.embeds")
    return _render(request, "features/embeds.html", user=user)


@router.post("/info-embed/save")
async def info_embed_save(server_id: int = Form(...), name: str = Form("info"),
                          title: str = Form(default=""), description: str = Form(default=""),
                          color: str = Form(default="#60a5fa"),
                          access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE)) -> Response:
    user = await _require_user(access_token)
    _require_cog("cogs.embeds.embeds")
    color_int = _hex_to_int(color, 0x60A5FA)
    async with db_session() as s:
        existing = await s.scalar(
            select(EmbedTemplate).where(
                EmbedTemplate.server_id == int(server_id),
                EmbedTemplate.key == name,
            )
        )
        if existing is None:
            s.add(EmbedTemplate(
                server_id=int(server_id), key=name[:64],
                title=title[:256], description=description, color=color_int,
            ))
        else:
            existing.title = title[:256]
            existing.description = description
            existing.color = color_int
        s.add(AuditLog(actor_id=user.id, action="info_embed.save", target=name))
    return RedirectResponse("/embeds", status_code=303)


# ---------- Members ----------------------------------------------------------

@router.get("/members", response_class=HTMLResponse)
async def members_view(request: Request,
                       q: str = "",
                       access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE)) -> HTMLResponse:
    user = await _require_user(access_token)
    _require_cog("cogs.moderation.moderation")
    server_id = _get_selected_server_id(request)
    members: list[dict[str, Any]] = []
    selected: int | None = None
    bot = get_bot()
    if server_id and bot is not None:
        sid = int(server_id)
        guild = bot.get_guild(sid) if sid else None
        if guild is not None:
            selected = guild.id
            ql = (q or "").strip().lower()
            for m in guild.members:
                if ql and ql not in m.name.lower() and ql not in str(m.id):
                    continue
                members.append({
                    "id": m.id,
                    "name": m.name,
                    "display_name": m.display_name,
                    "discriminator": m.discriminator,
                    "joined_at": m.joined_at.isoformat() if m.joined_at else "",
                    "roles": [{"id": r.id, "name": r.name, "color": r.colour.value} for r in m.roles if not r.is_default()],
                    "bot": m.bot,
                    "avatar": m.display_avatar.url if m.display_avatar else "",
                })
                if len(members) >= 500:
                    break
    return _render(
        request, "features/members.html", user=user,
        members=members, selected_server_id=selected, query=q,
    )


@router.post("/members/{server_id}/{member_id}/kick")
async def members_kick(server_id: int, member_id: int, reason: str = Form(default=""),
                       access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE)) -> Response:
    user = await _require_user(access_token)
    _require_cog("cogs.moderation.moderation")
    _, member = _get_guild_member(server_id, member_id)
    if member is not None:
        try:
            await member.kick(reason=f"web by {user.username}: {reason}")
        except discord.HTTPException:
            log.warning("member_kick_failed", member_id=member_id, exc_info=True)
    async with db_session() as s:
        s.add(AuditLog(actor_id=user.id, action="member.kick", target=str(member_id)))
    return RedirectResponse("/members", status_code=303)


@router.post("/members/{server_id}/{member_id}/ban")
async def members_ban(server_id: int, member_id: int, reason: str = Form(default=""),
                      access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE)) -> Response:
    user = await _require_user(access_token)
    _require_cog("cogs.moderation.moderation")
    guild, _ = _get_guild_member(server_id, member_id)
    if guild is not None:
        try:
            await guild.ban(_discord_obj(member_id), reason=f"web by {user.username}: {reason}")
        except discord.HTTPException:
            log.warning("member_ban_failed", member_id=member_id, exc_info=True)
    async with db_session() as s:
        s.add(AuditLog(actor_id=user.id, action="member.ban", target=str(member_id)))
    return RedirectResponse("/members", status_code=303)


@router.post("/members/{server_id}/{member_id}/timeout")
async def members_timeout(server_id: int, member_id: int,
                           minutes: int = Form(default=10),
                           reason: str = Form(default=""),
                           access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE)) -> Response:
    me = await _require_user(access_token)
    _require_cog("cogs.moderation.moderation")
    _, member = _get_guild_member(server_id, member_id)
    if member is not None:
        try:
            until = _dt2.now(tz=UTC) + _td2(minutes=max(1, min(40320, minutes)))
            await member.edit(timed_out_until=until, reason=f"web by {me.username}: {reason}")
        except discord.HTTPException:
            log.warning("member_timeout_failed", member_id=member_id, exc_info=True)
    async with db_session() as s:
        s.add(AuditLog(actor_id=me.id, action="member.timeout", target=str(member_id),
                       details={"minutes": minutes, "reason": reason}))
    return RedirectResponse("/members", status_code=303)


@router.post("/members/{server_id}/{member_id}/mute")
async def members_mute(server_id: int, member_id: int,
                        muted: str = Form(default="1"),
                        access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE)) -> Response:
    me = await _require_user(access_token)
    _require_cog("cogs.moderation.moderation")
    flag = _form_bool(muted)
    _, member = _get_guild_member(server_id, member_id)
    if member is not None and member.voice is not None:
        try:
            await member.edit(mute=flag, reason=f"web by {me.username}")
        except discord.HTTPException:
            log.warning("member_mute_failed", member_id=member_id, exc_info=True)
    async with db_session() as s:
        s.add(AuditLog(actor_id=me.id, action="member.mute", target=str(member_id), details={"mute": flag}))
    return RedirectResponse("/members", status_code=303)


@router.post("/members/{server_id}/{member_id}/deafen")
async def members_deafen(server_id: int, member_id: int,
                          deafened: str = Form(default="1"),
                          access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE)) -> Response:
    me = await _require_user(access_token)
    _require_cog("cogs.moderation.moderation")
    flag = _form_bool(deafened)
    _, member = _get_guild_member(server_id, member_id)
    if member is not None and member.voice is not None:
        try:
            await member.edit(deafen=flag, reason=f"web by {me.username}")
        except discord.HTTPException:
            log.warning("member_deafen_failed", member_id=member_id, exc_info=True)
    async with db_session() as s:
        s.add(AuditLog(actor_id=me.id, action="member.deafen", target=str(member_id), details={"deafen": flag}))
    return RedirectResponse("/members", status_code=303)


@router.post("/members/{server_id}/{member_id}/dm")
async def members_dm(server_id: int, member_id: int,
                      message: str = Form(...),
                      access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE)) -> Response:
    me = await _require_user(access_token)
    _require_cog("cogs.moderation.moderation")
    bot = get_bot()
    if bot is not None and message.strip():
        try:
            user_obj = bot.get_user(member_id) or await bot.fetch_user(member_id)
            if user_obj is not None:
                await user_obj.send(message[:1900])
        except discord.HTTPException:
            log.warning("member_dm_failed", member_id=member_id, exc_info=True)
    async with db_session() as s:
        s.add(AuditLog(actor_id=me.id, action="member.dm", target=str(member_id),
                       details={"length": len(message)}))
    return RedirectResponse("/members", status_code=303)


# ---------- Welcome / leave / boost -----------------------------------------

@router.get("/welcome", response_class=HTMLResponse)
async def welcome_view(request: Request,
                       access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE)) -> HTMLResponse:
    user = await _require_user(access_token)
    _require_cog("cogs.welcome.welcome")
    server_id = _get_selected_server_id(request)
    async with db_session() as s:
        cfg: ServerEventConfig | None = None
        if server_id:
            cfg = await s.get(ServerEventConfig, int(server_id))
    return _render(
        request, "features/welcome.html", user=user, cfg=cfg,
        selected_server_id=server_id,
    )


@router.post("/welcome/save")
async def welcome_save(
    server_id: int = Form(...),
    join_enabled: str = Form(default=""),
    join_channel_id: str = Form(default=""),
    join_title: str = Form(default=""),
    join_description: str = Form(default=""),
    join_color: str = Form(default="#60a5fa"),
    leave_enabled: str = Form(default=""),
    leave_channel_id: str = Form(default=""),
    leave_title: str = Form(default=""),
    leave_description: str = Form(default=""),
    leave_color: str = Form(default="#f43f5e"),
    boost_enabled: str = Form(default=""),
    boost_channel_id: str = Form(default=""),
    boost_title: str = Form(default=""),
    boost_description: str = Form(default=""),
    boost_color: str = Form(default="#a855f7"),
    access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE),
) -> Response:
    user = await _require_user(access_token)
    _require_cog("cogs.welcome.welcome")

    async with db_session() as s:
        cfg = await s.get(ServerEventConfig, int(server_id))
        if cfg is None:
            cfg = ServerEventConfig(server_id=int(server_id),
                                    join_embed={}, leave_embed={}, boost_embed={})
            s.add(cfg)
        cfg.join_enabled = _form_bool(join_enabled)
        cfg.join_channel_id = _form_channel_id(join_channel_id)
        cfg.join_embed = {
            "title": join_title, "description": join_description,
            "color": _hex_to_int(join_color, 0x60A5FA),
        }
        cfg.leave_enabled = _form_bool(leave_enabled)
        cfg.leave_channel_id = _form_channel_id(leave_channel_id)
        cfg.leave_embed = {
            "title": leave_title, "description": leave_description,
            "color": _hex_to_int(leave_color, 0xF43F5E),
        }
        cfg.boost_enabled = _form_bool(boost_enabled)
        cfg.boost_channel_id = _form_channel_id(boost_channel_id)
        cfg.boost_embed = {
            "title": boost_title, "description": boost_description,
            "color": _hex_to_int(boost_color, 0xA855F7),
        }
        s.add(AuditLog(actor_id=user.id, action="welcome.save", target=str(server_id)))
    return RedirectResponse("/welcome", status_code=303)


# ---------- Invite tracker ---------------------------------------------------

@router.get("/invites", response_class=HTMLResponse)
async def invites_view(
    request: Request,
    access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE),
) -> HTMLResponse:
    user = await _require_user(access_token)
    _require_cog("cogs.invite_tracker.invite_tracker")
    server_id = _get_selected_server_id(request)
    rows = []
    recent = []
    servers = []
    invite_error: str | None = None
    leaderboard: list[dict[str, Any]] = []
    try:
        async with db_session() as s:
            servers = (await s.scalars(select(Server).order_by(Server.name))).all()
            if server_id:
                stmt = (
                    select(InviteStats)
                    .where(InviteStats.server_id == int(server_id))
                    .order_by(desc(InviteStats.active_uses))
                    .limit(200)
                )
                rows = (await s.scalars(stmt)).all()
                for r in rows:
                    leaderboard.append({
                        "inviter_id": r.inviter_id,
                        "active_uses": r.active_uses,
                        "total_uses": r.total_uses,
                        "left_uses": r.left_uses,
                        "fake_uses": r.fake_uses,
                    })
            else:
                stmt = (
                    select(
                        InviteStats.inviter_id,
                        func.coalesce(func.sum(InviteStats.active_uses), 0).label("active_uses"),
                        func.coalesce(func.sum(InviteStats.total_uses), 0).label("total_uses"),
                        func.coalesce(func.sum(InviteStats.left_uses), 0).label("left_uses"),
                        func.coalesce(func.sum(InviteStats.fake_uses), 0).label("fake_uses"),
                    )
                    .group_by(InviteStats.inviter_id)
                    .order_by(desc(func.sum(InviteStats.active_uses)))
                    .limit(200)
                )
                agg = (await s.execute(stmt)).all()
                rows = []
                for r in agg:
                    leaderboard.append({
                        "inviter_id": r.inviter_id,
                        "active_uses": int(r.active_uses or 0),
                        "total_uses": int(r.total_uses or 0),
                        "left_uses": int(r.left_uses or 0),
                        "fake_uses": int(r.fake_uses or 0),
                    })
            recent_stmt = select(InviteUse).order_by(desc(InviteUse.created_at)).limit(50)
            if server_id:
                recent_stmt = recent_stmt.where(InviteUse.server_id == int(server_id))
            recent = (await s.scalars(recent_stmt)).all()
    except Exception as exc:
        invite_error = f"Invite-Daten konnten nicht geladen werden: {exc}"
    bot = get_bot()
    user_names: dict[int, str] = {}
    if bot is not None:
        for r in leaderboard:
            uid = r["inviter_id"]
            if uid and uid not in user_names:
                u = bot.get_user(uid)
                user_names[uid] = u.display_name if u else f"<@{uid}>"
        for r in recent:
            for uid in (r.inviter_id, r.invitee_id):
                if uid and uid not in user_names:
                    u = bot.get_user(uid)
                    user_names[uid] = u.display_name if u else f"<@{uid}>"
    return _render(
        request,
        "features/invites.html",
        user=user,
        servers=servers,
        stats=leaderboard,
        recent=recent,
        user_names=user_names,
        invite_error=invite_error,
        selected_server_id=int(server_id) if server_id else None,
    )


# ---------- Bot lifecycle API ------------------------------------------------

@router.post("/api/v1/bot/lifecycle/{action}")
async def bot_lifecycle(action: str,
                        access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE)) -> dict:
    user = await _require_user(access_token)
    if user.role != WebRole.ADMIN:
        raise HTTPException(403)
    from bot.runtime import request_bot_restart, request_bot_start, request_bot_stop
    if action == "start":
        request_bot_start()
    elif action == "stop":
        await request_bot_stop()
    elif action == "restart":
        await request_bot_restart()
    else:
        raise HTTPException(400, "unknown action")
    async with db_session() as s:
        s.add(AuditLog(actor_id=user.id, action=f"bot.{action}", target=""))
    return {"ok": True, "action": action}


# ---------- User settings API ------------------------------------------------

@router.get("/api/v1/user-settings/me")
async def user_settings_me(
    access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE),
) -> dict[str, Any]:
    from bot.pages._shared import _current_user
    user = await _current_user(access_token)
    if user is None:
        return dict(_DEFAULT_USER_SETTINGS)
    async with db_session() as s:
        row = await s.get(WebUserSettings, user.id)
    if row is None:
        return dict(_DEFAULT_USER_SETTINGS)
    extras = row.extras or {}
    return {
        "theme": row.theme,
        "accent_color": row.accent_color,
        "font_size": row.font_size,
        "compact_mode": extras.get("compact_mode", False),
        "reduce_motion": extras.get("reduce_motion", False),
        "refresh_interval": extras.get("refresh_interval", 5),
        "notifications_enabled": extras.get("notifications_enabled", True),
        "sidebar_collapsed": extras.get("sidebar_collapsed", False),
    }


# ---------- Channel/roles API ------------------------------------------------

@router.get("/api/v1/servers/{guild_id}/channels")
async def api_server_channels(
    guild_id: int,
    access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE),
) -> dict:
    await _require_user(access_token)
    bot = get_bot()
    if bot is None:
        return {"channels": [], "error": "bot_offline"}
    guild = bot.get_guild(int(guild_id))
    if guild is None:
        raise HTTPException(404, "guild not found")
    out: list[dict[str, Any]] = []
    for ch in sorted(guild.channels, key=lambda c: (c.position, c.id)):
        if isinstance(ch, discord.CategoryChannel):
            kind = "category"
        elif isinstance(ch, discord.VoiceChannel):
            kind = "voice"
        elif isinstance(ch, discord.StageChannel):
            kind = "stage"
        elif isinstance(ch, discord.ForumChannel):
            kind = "forum"
        else:
            kind = "text"
        cat = getattr(ch, "category", None)
        out.append({
            "id": str(ch.id),
            "name": ch.name,
            "type": kind,
            "category_id": str(cat.id) if cat else None,
            "category_name": cat.name if cat else None,
        })
    return {"channels": out}


@router.get("/api/v1/servers/{guild_id}/roles")
async def api_server_roles(
    guild_id: int,
    access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE),
) -> dict:
    await _require_user(access_token)
    bot = get_bot()
    if bot is None:
        return {"roles": [], "error": "bot_offline"}
    guild = bot.get_guild(int(guild_id))
    if guild is None:
        raise HTTPException(404, "guild not found")
    out: list[dict[str, Any]] = []
    for r in sorted(guild.roles, key=lambda r: -r.position):
        if r.is_default():
            continue
        out.append({
            "id": str(r.id),
            "name": r.name,
            "color": f"#{r.color.value:06x}" if r.color and r.color.value else "#99aab5",
            "member_count": len(r.members),
            "managed": r.managed,
        })
    return {"roles": out}


# ---------- Role permissions API ---------------------------------------------

_ROLE_PERMISSION_KEYS = (
    "tickets_create",
    "tickets_close",
    "giveaways_start",
    "backup_create",
    "moderation_use",
    "music_use",
)


@router.get("/api/v1/servers/{guild_id}/roles/{role_id}/permissions")
async def api_role_permissions_get(
    guild_id: int,
    role_id: int,
    access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE),
) -> dict:
    await _require_user(access_token)
    perms: dict[str, bool] = dict.fromkeys(_ROLE_PERMISSION_KEYS, False)
    async with db_session() as s:
        rows = (
            await s.scalars(
                select(RolePermission)
                .where(RolePermission.server_id == int(guild_id))
                .where(RolePermission.discord_role_id == int(role_id))
            )
        ).all()
        for r in rows:
            if r.command in perms:
                perms[r.command] = bool(r.allowed)
    return {"role_id": str(role_id), "permissions": perms}


@router.post("/api/v1/servers/{guild_id}/roles/{role_id}/permissions")
async def api_role_permissions_set(
    guild_id: int,
    role_id: int,
    payload: dict,
    access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE),
) -> dict:
    me = await _require_user(access_token)
    perms_in = payload.get("permissions") or {}
    if not isinstance(perms_in, dict):
        raise HTTPException(400, "permissions must be an object")
    async with db_session() as s:
        for key in _ROLE_PERMISSION_KEYS:
            value = bool(perms_in.get(key))
            row = await s.scalar(
                select(RolePermission)
                .where(RolePermission.server_id == int(guild_id))
                .where(RolePermission.discord_role_id == int(role_id))
                .where(RolePermission.command == key)
            )
            if row is None:
                s.add(RolePermission(
                    server_id=int(guild_id),
                    discord_role_id=int(role_id),
                    command=key,
                    allowed=value,
                ))
            else:
                row.allowed = value
        s.add(AuditLog(actor_id=me.id, action="role.permissions",
                       target=str(role_id), details={"server_id": str(guild_id)}))
    return {"ok": True}
