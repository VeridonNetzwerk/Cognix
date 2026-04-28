"""In-process bot reference for direct API <-> bot calls when Redis IPC is off.

The web layer (running in the same asyncio loop as the bot inside main.py)
can import :func:`get_bot` to access the live bot instance and act on
guilds/players directly. ``set_bot`` is called from ``run_bot`` once the
client is constructed.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from bot.client import CogniXBot

_BOT: "Optional[CogniXBot]" = None


def set_bot(bot: "CogniXBot") -> None:
    global _BOT
    _BOT = bot


def clear_bot() -> None:
    global _BOT
    _BOT = None


def get_bot() -> "Optional[CogniXBot]":
    return _BOT


def _format_uptime(seconds: float) -> str:
    seconds = int(max(0, seconds))
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours or days:
        parts.append(f"{hours}h")
    if minutes or hours or days:
        parts.append(f"{minutes}m")
    parts.append(f"{secs}s")
    return " ".join(parts)


def get_bot_info() -> dict[str, Any]:
    """Return a dict describing the live bot, suitable for injecting into
    template context or returning from a JSON endpoint.

    Always returns a populated dict; missing pieces fall back to defaults so
    templates never see ``None``.
    """
    bot = _BOT
    if bot is None or bot.user is None:
        return {
            "name": "CogniX",
            "username": "CogniX",
            "id": 0,
            "avatar_url": "",
            "online": False,
            "uptime": "\u2014",
            "uptime_seconds": 0,
            "latency_ms": 0.0,
            "guild_count": 0,
            "user_count": 0,
            "version": "0.1.0",
            "footer": "Powered by Cognix \u00b7 Made by \u98df\u3079\u7269",
        }
    start = getattr(bot, "start_time", 0.0) or time.time()
    uptime_seconds = max(0.0, time.time() - start)
    avatar = bot.user.display_avatar.url if bot.user.display_avatar else ""
    return {
        "name": bot.user.name,
        "username": str(bot.user),
        "id": bot.user.id,
        "avatar_url": avatar,
        "online": bot.is_ready(),
        "uptime": _format_uptime(uptime_seconds),
        "uptime_seconds": int(uptime_seconds),
        "latency_ms": round(bot.latency * 1000, 1) if bot.latency else 0.0,
        "guild_count": len(bot.guilds),
        "user_count": len({m.id for g in bot.guilds for m in g.members}) or sum(g.member_count or 0 for g in bot.guilds),
        "version": "0.1.0",
        "footer": "Powered by Cognix \u00b7 Made by \u98df\u3079\u7269",
    }


# --- per-server cog enablement cache --------------------------------------

_COG_STATE_CACHE: dict[tuple[int, str], tuple[bool, float]] = {}
_COG_STATE_TTL = 30.0  # seconds


async def is_cog_enabled_for_server(server_id: int, cog_name: str) -> bool:
    """Look up the per-server cog enable state. Cached for 30 s.

    Defaults to ``True`` when no row exists. Falls back to ``True`` on any DB
    error so a misconfigured DB doesn't silently brick all commands.
    """
    key = (server_id, cog_name)
    now = time.time()
    cached = _COG_STATE_CACHE.get(key)
    if cached is not None and (now - cached[1]) < _COG_STATE_TTL:
        return cached[0]
    try:
        from sqlalchemy import select  # local import to avoid cycle at boot

        from database.models.server_cog_state import ServerCogState
        from database.session import db_session

        async with db_session() as s:
            row = await s.scalar(
                select(ServerCogState).where(
                    ServerCogState.server_id == server_id,
                    ServerCogState.cog_name == cog_name,
                )
            )
            enabled = True if row is None else bool(row.enabled)
    except Exception:
        enabled = True
    _COG_STATE_CACHE[key] = (enabled, now)
    return enabled


def invalidate_cog_state_cache(server_id: int | None = None, cog_name: str | None = None) -> None:
    if server_id is None and cog_name is None:
        _COG_STATE_CACHE.clear()
        return
    for k in list(_COG_STATE_CACHE.keys()):
        if (server_id is None or k[0] == server_id) and (cog_name is None or k[1] == cog_name):
            _COG_STATE_CACHE.pop(k, None)


# --- bot lifecycle control (used by the dashboard buttons) ----------------

_BOT_PAUSED: bool = False


def set_bot_paused(paused: bool) -> None:
    """Toggle whether the supervisor in main._serve_bot should reconnect."""
    global _BOT_PAUSED
    _BOT_PAUSED = bool(paused)


def is_bot_paused() -> bool:
    return _BOT_PAUSED


async def request_bot_stop() -> None:
    """Close the running bot (stays disconnected until start is requested)."""
    set_bot_paused(True)
    bot = _BOT
    if bot is not None:
        try:
            await bot.close()
        except Exception:
            pass


async def request_bot_restart() -> None:
    """Close the running bot. The supervisor will reconnect automatically."""
    set_bot_paused(False)
    bot = _BOT
    if bot is not None:
        try:
            await bot.close()
        except Exception:
            pass


def request_bot_start() -> None:
    """Allow the supervisor loop to reconnect."""
    set_bot_paused(False)


# --- per-server config cache (FEAT #10) -----------------------------------

_GUILD_CFG_CACHE: dict[tuple[int, str], tuple[Any, float]] = {}
_GUILD_CFG_TTL = 60.0


def cache_guild_value(guild_id: int, key: str, value: Any) -> None:
    _GUILD_CFG_CACHE[(guild_id, key)] = (value, time.time())


def get_cached_guild_value(guild_id: int, key: str) -> Any | None:
    item = _GUILD_CFG_CACHE.get((guild_id, key))
    if item is None:
        return None
    value, ts = item
    if (time.time() - ts) > _GUILD_CFG_TTL:
        _GUILD_CFG_CACHE.pop((guild_id, key), None)
        return None
    return value


def invalidate_guild_cache(guild_id: int | None = None) -> None:
    if guild_id is None:
        _GUILD_CFG_CACHE.clear()
        return
    for k in list(_GUILD_CFG_CACHE.keys()):
        if k[0] == guild_id:
            _GUILD_CFG_CACHE.pop(k, None)
