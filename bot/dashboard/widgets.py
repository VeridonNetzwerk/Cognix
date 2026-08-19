"""Core dashboard widgets — always available regardless of loaded cogs."""

from __future__ import annotations

from sqlalchemy import desc, func, select

from bot.runtime import get_bot, get_bot_info
from bot.database.models.auth.audit_log import AuditLog
from bot.database.models.cogs.cog_state import CogState
from bot.database.models.giveaways.giveaway import Giveaway, GiveawayStatus
from bot.database.models.moderation.moderation import ModerationAction
from bot.database.models.server.server import Server
from bot.database.models.stats.discord_event import DiscordEvent
from bot.database.models.tickets.ticket import Ticket, TicketStatus

# Maps widget "size" strings to default grid dimensions (cols × rows)
WIDGET_SIZE_MAP: dict[str, tuple[int, int]] = {
    "small": (1, 1),
    "medium": (2, 1),
    "large": (2, 2),
    "wide": (4, 1),
    "tall": (1, 2),
}


def default_widget_size(size: str) -> tuple[int, int]:
    """Return (size_w, size_h) for a given size string, defaulting to 1×1."""
    return WIDGET_SIZE_MAP.get(size, (1, 1))


async def compute_metrics(session, user) -> dict:
    """Compute dashboard metrics (servers, users, cogs, tickets, bot status)."""
    servers_count = (await session.scalar(select(func.count(Server.id)))) or 0
    cogs_count = (await session.scalar(
        select(func.count(CogState.id)).where(CogState.enabled.is_(True))
    )) or 0
    open_tickets = (await session.scalar(
        select(func.count(Ticket.id)).where(Ticket.status == TicketStatus.OPEN)
    )) or 0

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
        users_count = (await session.scalar(
            select(func.coalesce(func.sum(Server.member_count), 0))
        )) or 0

    info = get_bot_info()
    return {
        "servers": servers_count,
        "users": users_count,
        "cogs_loaded": cogs_count,
        "open_tickets": open_tickets,
        "bot_online": info["online"],
        "uptime": info["uptime"],
        "latency_ms": info["latency_ms"],
        "guild_count": info["guild_count"],
        "user_count": users_count,
        "memory_mb": info.get("memory_mb", 0.0),
        "version": info["version"],
    }


async def load_widget_data(session, active_widget_ids: list[str], recent: list | None = None) -> dict[str, dict]:
    """Load fresh data for all active widgets."""
    widget_data: dict[str, dict] = {}
    for wid in active_widget_ids:
        if wid == "moderation_recent":
            rows = (await session.scalars(
                select(ModerationAction).order_by(desc(ModerationAction.created_at)).limit(10)
            )).all()
            widget_data[wid] = {"moderation_recent": rows}
        elif wid == "tickets_open":
            tickets = (await session.scalars(
                select(Ticket).where(Ticket.status == TicketStatus.OPEN).order_by(desc(Ticket.created_at)).limit(5)
            )).all()
            widget_data[wid] = {
                "tickets_open": tickets,
                "tickets_open_count": len(tickets),
            }
        elif wid == "giveaways_active":
            giveaways = (await session.scalars(
                select(Giveaway).where(Giveaway.status == GiveawayStatus.ACTIVE).order_by(Giveaway.ends_at).limit(5)
            )).all()
            widget_data[wid] = {"giveaways_active": giveaways}
        elif wid == "activity_recent":
            events = (await session.scalars(
                select(DiscordEvent).order_by(desc(DiscordEvent.created_at)).limit(10)
            )).all()
            widget_data[wid] = {"activity_recent": events}
        elif wid == "welcome_recent":
            join_events = (await session.scalars(
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
            msg_count = (await session.scalar(
                select(func.count(StatEvent.id)).where(StatEvent.event_type == StatEventType.MESSAGE)
            )) or 0
            cmd_count = (await session.scalar(
                select(func.count(StatEvent.id)).where(StatEvent.event_type == StatEventType.COMMAND)
            )) or 0
            join_count = (await session.scalar(
                select(func.count(StatEvent.id)).where(StatEvent.event_type == StatEventType.MEMBER_JOIN)
            )) or 0
            leave_count = (await session.scalar(
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
        elif wid == "recent_audit":
            widget_data[wid] = {"recent_audit": recent or []}
    return widget_data


CORE_WIDGETS = [
    {
        "id": "bot_status",
        "title": "Bot Status",
        "template": "widgets/bot_status.html",
        "size": "medium",
        "icon": "ph-robot",
        "cog": "__core__",
    },
    {
        "id": "metrics_overview",
        "title": "Overview",
        "template": "widgets/metrics_overview.html",
        "size": "medium",
        "icon": "ph-gauge",
        "cog": "__core__",
    },
]
