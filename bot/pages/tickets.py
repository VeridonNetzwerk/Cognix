"""Tickets, ticket settings, ticket detail, ticket types, and panels routes."""

from __future__ import annotations

import uuid

from fastapi import Cookie, Form, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import desc, select

from bot.runtime import get_bot
from bot.database.models.stats.discord_message_cache import DiscordMessageCache
from bot.database.models.server.server import Server
from bot.database.models.server.server_config import ServerConfig
from bot.database.models.tickets.ticket import Ticket, TicketStatus
from bot.database.models.tickets.ticket_panel import TicketPanel, TicketType
from bot.database.session import db_session
from web.deps import ACCESS_COOKIE
from bot.pages._shared import _render, _require_cog, _require_user, router


@router.get("/tickets", response_class=HTMLResponse)
async def tickets_view(request: Request,
                       status_filter: str | None = None,
                       access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE)) -> HTMLResponse:
    user = await _require_user(access_token)
    _require_cog("bot.cogs.tickets.tickets")
    async with db_session() as s:
        q = select(Ticket).order_by(desc(Ticket.created_at)).limit(200)
        if status_filter in ("open", "closed", "archived"):
            q = q.where(Ticket.status == TicketStatus(status_filter))
        tickets = (await s.scalars(q)).all()
        servers = (await s.scalars(select(Server).order_by(Server.name))).all()
    return _render(
        request,
        "tickets/tickets.html",
        user=user,
        tickets=tickets,
        servers=servers,
        status_filter=status_filter or "",
    )


@router.post("/tickets/{ticket_id}/close")
async def tickets_close(ticket_id: str,
                        access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE)) -> Response:
    await _require_user(access_token)
    _require_cog("bot.cogs.tickets.tickets")
    from web.services.bot_ipc import get_ipc
    try:
        await get_ipc().call("ticket.close", {"ticket_id": ticket_id}, timeout=5.0)
    except Exception:
        bot = get_bot()
        if bot is not None:
            cog = bot.get_cog("Tickets")
            if cog is not None:
                await cog._ipc_close({"ticket_id": ticket_id})  # type: ignore[attr-defined]
    return RedirectResponse("/tickets", status_code=303)


@router.post("/tickets/save")
async def tickets_save(server_id: int = Form(...),
                       ticket_category_id: str = Form(default=""),
                       ticket_support_role_ids: str = Form(default=""),
                       access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE)) -> Response:
    await _require_user(access_token)
    _require_cog("bot.cogs.tickets.tickets")
    role_ids = [int(x.strip()) for x in ticket_support_role_ids.split(",") if x.strip().isdigit()]
    async with db_session() as s:
        cfg = await s.get(ServerConfig, server_id)
        if cfg is None:
            cfg = ServerConfig(server_id=server_id)
            s.add(cfg)
        cfg.ticket_category_id = int(ticket_category_id) if ticket_category_id.strip().isdigit() else None
        cfg.ticket_support_role_ids = role_ids
    return RedirectResponse("/tickets", status_code=303)


@router.get("/tickets/archive", response_class=HTMLResponse)
async def tickets_archive(request: Request,
                          access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE)) -> HTMLResponse:
    user = await _require_user(access_token)
    _require_cog("bot.cogs.tickets.tickets")
    async with db_session() as s:
        tickets = (await s.scalars(
            select(Ticket)
            .where(Ticket.status.in_([TicketStatus.CLOSED, TicketStatus.ARCHIVED]))
            .order_by(desc(Ticket.created_at))
            .limit(500)
        )).all()
        servers = (await s.scalars(select(Server).order_by(Server.name))).all()
    return _render(
        request,
        "tickets/tickets.html",
        user=user,
        tickets=tickets,
        servers=servers,
        status_filter="archived",
        archive_view=True,
    )


@router.get("/tickets/settings", response_class=HTMLResponse)
async def tickets_settings(request: Request,
                            access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE)) -> HTMLResponse:
    user = await _require_user(access_token)
    _require_cog("bot.cogs.tickets.tickets")
    async with db_session() as s:
        servers = (await s.scalars(select(Server).order_by(Server.name))).all()
        configs = (await s.scalars(select(ServerConfig))).all()
    cfg_by_server = {c.server_id: c for c in configs}
    return _render(
        request,
        "tickets/ticket_settings.html",
        user=user,
        servers=servers,
        cfg_by_server=cfg_by_server,
    )


@router.get("/tickets/{ticket_id}", response_class=HTMLResponse)
async def ticket_view(
    ticket_id: str,
    request: Request,
    access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE),
) -> HTMLResponse:
    user = await _require_user(access_token)
    _require_cog("bot.cogs.tickets.tickets")
    async with db_session() as s:
        ticket = await s.get(Ticket, uuid.UUID(ticket_id))
        if ticket is None:
            from fastapi import HTTPException
            raise HTTPException(404)
        msgs = (
            await s.scalars(
                select(DiscordMessageCache)
                .where(DiscordMessageCache.channel_id == ticket.channel_id)
                .order_by(DiscordMessageCache.created_at.asc())
            )
        ).all()
    return _render(request, "tickets/ticket_detail.html", user=user, ticket=ticket, messages=msgs)


# ---------- Ticket types & panels ---------------------------------------------

@router.get("/ticket-types", response_class=HTMLResponse)
async def ticket_types_view(request: Request,
                            access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE)) -> HTMLResponse:
    user = await _require_user(access_token)
    async with db_session() as s:
        types = (await s.scalars(select(TicketType).order_by(TicketType.created_at))).all()
        servers = (await s.scalars(select(Server).order_by(Server.name))).all()
    return _render(request, "tickets/ticket_types.html", user=user, types=types, servers=servers)


@router.post("/ticket-types/create")
async def ticket_types_create(server_id: int = Form(...), name: str = Form(...),
                              description: str = Form(default=""), emoji: str = Form(default=""),
                              category_id: str = Form(default=""), ping_role_id: str = Form(default=""),
                              access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE)) -> Response:
    user = await _require_user(access_token)
    async with db_session() as s:
        t = TicketType(
            server_id=int(server_id), name=name[:64], description=description[:256],
            emoji=emoji[:16],
            category_id=int(category_id) if category_id.strip().isdigit() else None,
            ping_role_id=int(ping_role_id) if ping_role_id.strip().isdigit() else None,
            welcome_embed={},
        )
        s.add(t)
        from bot.database.models.auth.audit_log import AuditLog
        s.add(AuditLog(actor_id=user.id, action="ticket_type.create", target=name))
    return RedirectResponse("/ticket-types", status_code=303)


@router.post("/ticket-types/{type_id}/delete")
async def ticket_types_delete(type_id: str,
                              access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE)) -> Response:
    user = await _require_user(access_token)
    async with db_session() as s:
        t = await s.get(TicketType, uuid.UUID(type_id))
        if t is not None:
            from bot.database.models.auth.audit_log import AuditLog
            s.add(AuditLog(actor_id=user.id, action="ticket_type.delete", target=t.name))
            await s.delete(t)
    return RedirectResponse("/ticket-types", status_code=303)


@router.get("/ticket-panels", response_class=HTMLResponse)
async def ticket_panels_view(request: Request,
                             access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE)) -> HTMLResponse:
    user = await _require_user(access_token)
    async with db_session() as s:
        panels = (await s.scalars(select(TicketPanel).order_by(TicketPanel.created_at))).all()
        types = (await s.scalars(select(TicketType).order_by(TicketType.name))).all()
        servers = (await s.scalars(select(Server).order_by(Server.name))).all()
    return _render(request, "tickets/ticket_panels.html", user=user, panels=panels, types=types, servers=servers)


@router.post("/ticket-panels/create")
async def ticket_panels_create(server_id: int = Form(...), name: str = Form(...),
                               access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE)) -> Response:
    user = await _require_user(access_token)
    async with db_session() as s:
        p = TicketPanel(server_id=int(server_id), name=name[:64], embed={}, buttons=[])
        s.add(p)
        from bot.database.models.auth.audit_log import AuditLog
        s.add(AuditLog(actor_id=user.id, action="ticket_panel.create", target=name))
    return RedirectResponse("/ticket-panels", status_code=303)


@router.post("/ticket-panels/{panel_id}/delete")
async def ticket_panels_delete(panel_id: str,
                               access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE)) -> Response:
    user = await _require_user(access_token)
    async with db_session() as s:
        p = await s.get(TicketPanel, uuid.UUID(panel_id))
        if p is not None:
            from bot.database.models.auth.audit_log import AuditLog
            s.add(AuditLog(actor_id=user.id, action="ticket_panel.delete", target=p.name))
            await s.delete(p)
    return RedirectResponse("/ticket-panels", status_code=303)
