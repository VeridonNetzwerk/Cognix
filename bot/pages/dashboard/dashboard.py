"""Dashboard, servers, and server detail routes."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import Cookie, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import desc, func, select

from bot.runtime import get_bot, get_bot_info
from bot.cogs.registry import get_available_widgets
from bot.dashboard.widgets import CORE_WIDGETS
from bot.database.models.auth.audit_log import AuditLog
from bot.database.models.auth.user_dashboard_widget import UserDashboardWidget
from bot.database.models.cogs.cog_state import CogState
from bot.database.models.auth.role_permission import RolePermission
from bot.database.models.giveaways.giveaway import Giveaway, GiveawayStatus
from bot.database.models.moderation.moderation import ModerationAction
from bot.database.models.server.server import Server
from bot.database.models.server.server_config import ServerConfig
from bot.database.models.stats.discord_event import DiscordEvent
from bot.database.models.tickets.ticket import Ticket, TicketStatus
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

    # --- Widget system ---
    # 1. Collect available widgets: core + cog-provided
    available_widgets = list(CORE_WIDGETS)
    available_widgets.extend(get_available_widgets())

    # 2. Load user's widget layout from DB
    async with db_session() as s:
        user_widgets = (await s.scalars(
            select(UserDashboardWidget)
            .where(UserDashboardWidget.user_id == user.id)
            .order_by(UserDashboardWidget.position)
        )).all()
    user_layout = {w.widget_id: w for w in user_widgets}

    # 3. Build active widget list: user's visible widgets in order, filtered by availability
    active_widget_ids = [
        w.widget_id for w in user_widgets
        if w.visible and any(aw["id"] == w.widget_id for aw in available_widgets)
    ]

    # If no layout saved yet, show default widgets
    if not active_widget_ids:
        active_widget_ids = ["metrics_overview", "bot_status", "recent_audit"]

    # 4. Build ordered widget list with data
    widget_by_id = {w["id"]: w for w in available_widgets}
    active_widgets = []
    for wid in active_widget_ids:
        w_info = widget_by_id.get(wid)
        if w_info is None:
            continue
        w_copy = dict(w_info)
        # Attach user's size preferences
        uw = user_layout.get(wid)
        if uw:
            w_copy["size_w"] = uw.size_w or 1
            w_copy["size_h"] = uw.size_h or 1
        else:
            w_copy.setdefault("size_w", 1)
            w_copy.setdefault("size_h", 1)
        active_widgets.append(w_copy)

    # 5. Load widget data (async queries per widget type)
    widget_data: dict[str, dict] = {}
    async with db_session() as s:
        for w in active_widgets:
            wid = w["id"]
            if wid == "moderation_recent":
                rows = (await s.scalars(
                    select(ModerationAction).order_by(desc(ModerationAction.created_at)).limit(10)
                )).all()
                widget_data[wid] = {"moderation_recent": rows}
            elif wid == "tickets_open":
                tickets = (await s.scalars(
                    select(Ticket).where(Ticket.status == TicketStatus.OPEN).order_by(desc(Ticket.created_at)).limit(5)
                )).all()
                widget_data[wid] = {
                    "tickets_open": tickets,
                    "tickets_open_count": len(tickets),
                }
            elif wid == "giveaways_active":
                giveaways = (await s.scalars(
                    select(Giveaway).where(Giveaway.status == GiveawayStatus.ACTIVE).order_by(Giveaway.ends_at).limit(5)
                )).all()
                widget_data[wid] = {"giveaways_active": giveaways}
            elif wid == "activity_recent":
                events = (await s.scalars(
                    select(DiscordEvent).order_by(desc(DiscordEvent.created_at)).limit(10)
                )).all()
                widget_data[wid] = {"activity_recent": events}
            elif wid == "welcome_recent":
                # Get recent member joins from DiscordEvent
                join_events = (await s.scalars(
                    select(DiscordEvent)
                    .where(DiscordEvent.event_type == "member_join")
                    .order_by(desc(DiscordEvent.created_at)).limit(10)
                )).all()
                members = [
                    {
                        "display_name": e.summary or "Unknown",
                        "avatar_url": None,
                        "joined_at": e.created_at,
                    }
                    for e in join_events
                ]
                widget_data[wid] = {"welcome_recent": members}
            elif wid == "stats_overview":
                from bot.database.models.stats.stats import StatEvent, StatEventType
                msg_count = (await s.scalar(
                    select(func.count(StatEvent.id)).where(StatEvent.event_type == StatEventType.MESSAGE)
                )) or 0
                cmd_count = (await s.scalar(
                    select(func.count(StatEvent.id)).where(StatEvent.event_type == StatEventType.COMMAND)
                )) or 0
                join_count = (await s.scalar(
                    select(func.count(StatEvent.id)).where(StatEvent.event_type == StatEventType.MEMBER_JOIN)
                )) or 0
                leave_count = (await s.scalar(
                    select(func.count(StatEvent.id)).where(StatEvent.event_type == StatEventType.MEMBER_LEAVE)
                )) or 0
                widget_data[wid] = {
                    "stats_messages": msg_count,
                    "stats_commands": cmd_count,
                    "stats_joins": join_count,
                    "stats_leaves": leave_count,
                }
            elif wid == "music_now_playing":
                widget_data[wid] = {"music_now_playing": None}
            elif wid == "music_queue":
                widget_data[wid] = {"music_queue": []}

    # Available widgets not yet on dashboard (for add menu)
    available_to_add = [
        w for w in available_widgets
        if w["id"] not in active_widget_ids
    ]

    return _render(
        request,
        "dashboard/dashboard.html",
        user=user,
        metrics=metrics,
        recent_audit=recent,
        can_servers_write=can_servers_write,
        active_widgets=active_widgets,
        available_widgets=available_widgets,
        available_to_add=available_to_add,
        widget_data=widget_data,
    )


@router.get("/servers", response_class=HTMLResponse)
async def servers_view(request: Request,
                       access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE)) -> HTMLResponse:
    user = await _require_user(access_token)
    async with db_session() as s:
        rows = (await s.scalars(select(Server).order_by(Server.name))).all()
    return _render(request, "dashboard/servers.html", user=user, servers=rows)


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
        "dashboard/server_detail.html",
        user=user,
        server=srv,
        config=cfg or {},
        permissions=perms,
    )
