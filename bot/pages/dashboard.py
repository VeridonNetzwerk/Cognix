"""Dashboard, servers, and server detail routes."""

from __future__ import annotations

from fastapi import Cookie, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import desc, func, select

from bot.runtime import get_bot, get_bot_info
from bot.database.models.audit_log import AuditLog
from bot.database.models.cog_state import CogState
from bot.database.models.role_permission import RolePermission
from bot.database.models.server import Server
from bot.database.models.server_config import ServerConfig
from bot.database.models.ticket import Ticket, TicketStatus
from bot.database.session import db_session
from web.deps import ACCESS_COOKIE
from bot.pages._shared import (
    _current_user,
    _render,
    _require_user,
    _system_configured,
    router,
)


@router.get("/", response_class=HTMLResponse)
async def index(request: Request,
                access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE)) -> HTMLResponse:
    if not await _system_configured():
        return RedirectResponse("/setup", status_code=303)
    user = await _current_user(access_token)
    if user is None:
        return RedirectResponse("/login", status_code=303)

    async with db_session() as s:
        servers_count = (await s.scalar(select(func.count(Server.id)))) or 0
        cogs_count = (await s.scalar(
            select(func.count(CogState.id)).where(CogState.enabled.is_(True))
        )) or 0
        open_tickets = (await s.scalar(
            select(func.count(Ticket.id)).where(Ticket.status == TicketStatus.OPEN)
        )) or 0
        recent = (await s.scalars(
            select(AuditLog).order_by(desc(AuditLog.created_at)).limit(8)
        )).all()
        from web.security.permissions import has_permission as _hp
        can_servers_write = await _hp(s, user, "servers", level="write")

    bot = get_bot()
    if bot is not None:
        unique_ids: set[int] = set()
        for g in bot.guilds:
            for m in g.members:
                unique_ids.add(m.id)
        users_count = len(unique_ids)
        if users_count == 0:
            users_count = sum(g.member_count or 0 for g in bot.guilds)
    else:
        async with db_session() as s2:
            users_count = (await s2.scalar(
                select(func.coalesce(func.sum(Server.member_count), 0))
            )) or 0

    info = get_bot_info()
    metrics = {
        "servers": servers_count,
        "users": users_count,
        "cogs_loaded": cogs_count,
        "open_tickets": open_tickets,
        "bot_online": info["online"],
        "uptime": info["uptime"],
        "latency_ms": info["latency_ms"],
        "guild_count": info["guild_count"],
        "user_count": users_count,
        "version": info["version"],
    }
    return _render(request, "dashboard.html", user=user, metrics=metrics, recent_audit=recent,
                   can_servers_write=can_servers_write)


@router.get("/servers", response_class=HTMLResponse)
async def servers_view(request: Request,
                       access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE)) -> HTMLResponse:
    user = await _require_user(access_token)
    async with db_session() as s:
        rows = (await s.scalars(select(Server).order_by(Server.name))).all()
    return _render(request, "servers.html", user=user, servers=rows)


@router.get("/servers/{server_id}", response_class=HTMLResponse)
async def server_detail(request: Request, server_id: int,
                        access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE)) -> HTMLResponse:
    user = await _require_user(access_token)
    async with db_session() as s:
        srv = await s.get(Server, server_id)
        cfg = await s.get(ServerConfig, server_id)
        perms = (
            await s.scalars(
                select(RolePermission).where(RolePermission.server_id == server_id)
            )
        ).all()
    if srv is None:
        return _render(request, "error.html", user=user, status=404,
                       title="Server not found", detail="No such server.")
    return _render(
        request,
        "server_detail.html",
        user=user,
        server=srv,
        config=cfg or {},
        permissions=perms,
    )
