"""Audit log, Discord event log, and combined log routes."""

from __future__ import annotations

import uuid
from datetime import datetime as _dt

from fastapi import Cookie, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import desc, select

from bot.database.models.audit_log import AuditLog
from bot.database.models.discord_event import DiscordEvent, DiscordEventType
from bot.database.models.server import Server
from bot.database.models.web_user import WebRole, WebUser
from bot.database.session import db_session
from web.deps import ACCESS_COOKIE
from bot.pages._shared import _render, _require_cog, _require_user, router


@router.get("/audit", response_class=HTMLResponse)
async def audit_view(request: Request,
                     action: str | None = None,
                     actor_id: str | None = None,
                     date_from: str | None = None,
                     date_to: str | None = None,
                     access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE)) -> HTMLResponse:
    user = await _require_user(access_token)
    if user.role != WebRole.ADMIN:
        return _render(request, "error.html", user=user, status=403,
                       title="Forbidden", detail="Admin only.")
    async with db_session() as s:
        q = select(AuditLog).order_by(desc(AuditLog.created_at)).limit(500)
        if action:
            q = q.where(AuditLog.action.ilike(f"%{action}%"))
        if actor_id:
            try:
                q = q.where(AuditLog.actor_id == uuid.UUID(actor_id))
            except ValueError:
                pass
        if date_from:
            try:
                q = q.where(AuditLog.created_at >= _dt.fromisoformat(date_from))
            except ValueError:
                pass
        if date_to:
            try:
                q = q.where(AuditLog.created_at <= _dt.fromisoformat(date_to))
            except ValueError:
                pass
        rows = (await s.scalars(q)).all()
    return _render(
        request,
        "audit.html",
        user=user,
        events=rows,
        filters={
            "action": action or "",
            "actor_id": actor_id or "",
            "date_from": date_from or "",
            "date_to": date_to or "",
        },
    )


@router.get("/discord-log", response_class=HTMLResponse)
async def discord_log_view(request: Request,
                           server_id: str | None = None,
                           event_type: str | None = None,
                           user_id: str | None = None,
                           date_from: str | None = None,
                           date_to: str | None = None,
                           access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE)) -> HTMLResponse:
    me = await _require_user(access_token)
    _require_cog("bot.cogs.activity_log")
    if me.role == WebRole.VIEWER:
        return _render(request, "error.html", user=me, status=403,
                       title="Forbidden", detail="Moderator+ only.")
    async with db_session() as s:
        q = select(DiscordEvent).order_by(desc(DiscordEvent.created_at)).limit(500)
        if server_id and server_id.isdigit():
            q = q.where(DiscordEvent.server_id == int(server_id))
        if event_type:
            try:
                q = q.where(DiscordEvent.event_type == DiscordEventType(event_type))
            except ValueError:
                pass
        if user_id and user_id.isdigit():
            q = q.where(DiscordEvent.user_id == int(user_id))
        if date_from:
            try:
                q = q.where(DiscordEvent.created_at >= _dt.fromisoformat(date_from))
            except ValueError:
                pass
        if date_to:
            try:
                q = q.where(DiscordEvent.created_at <= _dt.fromisoformat(date_to))
            except ValueError:
                pass
        rows = (await s.scalars(q)).all()
        servers = (await s.scalars(select(Server).order_by(Server.name))).all()
    server_lookup = {sv.id: sv.name for sv in servers}
    return _render(
        request,
        "discord_log.html",
        user=me,
        events=rows,
        servers=servers,
        server_lookup=server_lookup,
        event_types=[t.value for t in DiscordEventType],
        filters={
            "server_id": server_id or "",
            "event_type": event_type or "",
            "user_id": user_id or "",
            "date_from": date_from or "",
            "date_to": date_to or "",
        },
    )


@router.get("/log", response_class=HTMLResponse)
async def log_view(request: Request, tab: str = "web",
                   access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE)) -> HTMLResponse:
    from typing import Any
    user = await _require_user(access_token)
    _require_cog("bot.cogs.activity_log")
    if tab not in ("web", "discord"):
        tab = "web"
    web_rows: list[Any] = []
    discord_rows: list[Any] = []
    actor_names: dict[str, str] = {}
    async with db_session() as s:
        if tab == "web":
            web_rows = (await s.scalars(
                select(AuditLog).order_by(desc(AuditLog.created_at)).limit(200)
            )).all()
            actor_ids = {r.actor_id for r in web_rows if r.actor_id is not None}
            if actor_ids:
                users = (await s.scalars(
                    select(WebUser).where(WebUser.id.in_(actor_ids))
                )).all()
                actor_names = {str(u.id): u.username for u in users}
        else:
            discord_rows = (await s.scalars(
                select(DiscordEvent).order_by(desc(DiscordEvent.created_at)).limit(200)
            )).all()
    return _render(
        request, "log.html", user=user, tab=tab, web_rows=web_rows,
        discord_rows=discord_rows, actor_names=actor_names,
    )
