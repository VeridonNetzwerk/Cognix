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
    """Format uptime to a human-readable string.

    Only shows units that are non-zero, stopping at the first zero unit
    (so 5 seconds → "5s", not "0h 0m 5s").
    """
    seconds = int(max(0, seconds))
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    parts: list[str] = []
    if days:
        parts.append(f"{days}d")
    if parts or hours:
        parts.append(f"{hours}h")
    if parts or minutes:
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
    # Compute user count — try fast path first (unique member objects),
    # then fall back to guild.member_count.
    user_count = len({m.id for g in bot.guilds for m in g.members})
    if user_count == 0:
        user_count = sum(g.member_count or 0 for g in bot.guilds)
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
        "user_count": user_count,
        "version": "0.1.0",
        "footer": "Powered by Cognix \u00b7 Made by \u98df\u3079\u7269",
    }


# --- per-server cog enablement cache --------------------------------------

_COG_STATE_CACHE: dict[tuple[int, str], tuple[bool, float]] = {}
_COG_STATE_TTL = 30.0  # seconds
# Max entries before full GC to prevent unbounded memory growth
_COG_STATE_MAX_ENTRIES = 5000


async def is_cog_enabled_for_server(server_id: int, cog_name: str) -> bool:
    """Look up whether a cog is both loaded AND enabled for a server.

    Returns True only when ALL of the following are true:
    1. The cog is loaded globally (bot has its extension loaded)
    2. ServerCogState exists and is enabled, OR no row exists (defaults to True)
    3. SystemConfig.enabled_cobs for this server includes the cog name

    Defaults to ``True`` when no DB data exists. Falls back to ``True`` on any DB
    error so a misconfigured DB doesn't silently brick all commands.
    """
    key = (server_id, cog_name)
    now = time.time()
    cached = _COG_STATE_CACHE.get(key)
    if cached is not None and (now - cached[1]) < _COG_STATE_TTL:
        return cached[0]
    try:
        from sqlalchemy import select  # local import to avoid cycle at boot

        from database.models.server_config import ServerConfig
        from database.session import db_session

        async with db_session() as s:
            cfg = await s.scalar(
                select(ServerConfig).where(ServerConfig.server_id == server_id)
            )
            # Check if cog is in enabled_cogs list (if the config exists)
            if cfg and cfg.enabled_cogs:
                if cog_name.lower() not in [c.lower() for c in cfg.enabled_cogs]:
                    _COG_STATE_CACHE[key] = (False, now)
                    return False
    except Exception:  # noqa: BLE001
        pass

    # Default behavior: enabled unless explicitly disabled
    enabled = True
    _COG_STATE_CACHE[key] = (enabled, now)
    # Prune cache if it grows beyond limit
    if len(_COG_STATE_CACHE) > _COG_STATE_MAX_ENTRIES:
        stale = [
            k for k, (_, ts) in _COG_STATE_CACHE.items() if (now - ts) > _COG_STATE_TTL
        ]
        for k in stale:
            _COG_STATE_CACHE.pop(k, None)
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
# Async event used by the supervisor loop in main._serve_bot to wake up
# instantly when start/restart is requested. Lazily created on the running
# event loop so this module stays import-safe at startup.
_RESUME_EVENT: "asyncio.Event | None" = None  # noqa: F821 (asyncio imported below)


def _resume_event() -> "asyncio.Event":  # noqa: F821
    import asyncio as _asyncio
    global _RESUME_EVENT
    if _RESUME_EVENT is None:
        _RESUME_EVENT = _asyncio.Event()
    return _RESUME_EVENT


async def wait_for_resume(timeout: float) -> bool:
    """Block until a start/restart was requested or ``timeout`` elapses.

    Returns True if a resume was signalled, False on timeout.
    """
    import asyncio as _asyncio
    ev = _resume_event()
    try:
        await _asyncio.wait_for(ev.wait(), timeout=timeout)
        ev.clear()
        return True
    except _asyncio.TimeoutError:
        return False


def set_bot_paused(paused: bool) -> None:
    """Toggle whether the supervisor in main._serve_bot should reconnect."""
    global _BOT_PAUSED
    _BOT_PAUSED = bool(paused)
    if not _BOT_PAUSED:
        try:
            _resume_event().set()
        except RuntimeError:
            # No running loop — supervisor will pick up the flag on its next tick.
            pass


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
