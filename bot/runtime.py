"""In-process bot reference for direct API <-> bot calls when Redis IPC is off.

The web layer (running in the same asyncio loop as the bot inside main.py)
can import :func:`get_bot` to access the live bot instance and act on
guilds/players directly. ``set_bot`` is called from ``run_bot`` once the
client is constructed.
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from bot.client import CogniXBot

_BOT: "Optional[CogniXBot]" = None
_BOT_ERROR: str | None = None


def set_bot(bot: "CogniXBot") -> None:
    global _BOT
    _BOT = bot


def clear_bot() -> None:
    global _BOT
    _BOT = None


def get_bot() -> "Optional[CogniXBot]":
    return _BOT


def set_bot_error(error: str | None) -> None:
    """Store the last bot connection/login error so the web layer can surface it."""
    global _BOT_ERROR
    _BOT_ERROR = error


def clear_bot_error() -> None:
    global _BOT_ERROR
    _BOT_ERROR = None


def get_bot_error() -> str | None:
    return _BOT_ERROR


# --- live ping monitor (gateway heartbeat with smoothing) ----------------
# The monitor samples bot.latency (discord.py's gateway heartbeat round-trip)
# every 2 seconds and applies exponential smoothing to eliminate spikes.
_PING_MS: float | None = None
_PING_AT: float = 0.0
_PING_ERROR: str | None = None


def get_ping_ms() -> float | None:
    """Return the last measured active ping in ms, or None if never measured."""
    return _PING_MS


def get_ping_info() -> dict[str, Any]:
    return {"ms": _PING_MS, "at": _PING_AT, "error": _PING_ERROR}


async def run_ping_monitor(bot: "CogniXBot") -> None:
    """Continuously measure Discord latency. Runs until the bot is closed.

    Uses the gateway heartbeat latency (bot.latency) which is a stable
    rolling average maintained by discord.py's websocket protocol. We sample
    it every 2 seconds and apply exponential smoothing to eliminate spikes.
    """
    from bot.config.logging import get_logger

    log = get_logger("bot.ping")
    log.info("ping_monitor_started")
    global _PING_MS, _PING_AT, _PING_ERROR
    while not bot.is_closed():
        if bot.is_ready():
            try:
                # Use gateway heartbeat latency — stable, no extra API calls
                raw = bot.latency
                if raw is not None and raw >= 0:
                    raw_ms = round(raw * 1000, 1)
                    # Exponential smoothing: blend new sample with previous
                    # to eliminate transient spikes (alpha=0.3 = 30% new, 70% old)
                    if _PING_MS is not None and _PING_MS > 0:
                        _PING_MS = round(_PING_MS * 0.7 + raw_ms * 0.3, 1)
                    else:
                        _PING_MS = raw_ms
                    _PING_AT = time.time()
                    _PING_ERROR = None
            except Exception as exc:  # noqa: BLE001
                _PING_ERROR = str(exc)
                log.warning("ping_measure_failed", error=str(exc))
        # Sample every 2 seconds — gateway heartbeat updates ~every 40s,
        # but this keeps the timestamp fresh and catches disconnects quickly
        try:
            await asyncio.sleep(2.0)
        except asyncio.CancelledError:
            break
    log.info("ping_monitor_stopped")


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


def _format_age(created_at) -> str:
    """Format how long ago a datetime was, e.g. '2 Jahren, 3 Monaten'."""
    from datetime import datetime, timezone

    if hasattr(created_at, 'tzinfo') and created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    now = datetime.now(tz=timezone.utc)
    delta = now - created_at
    days = delta.days
    years = days // 365
    remaining_days = days % 365
    months = remaining_days // 30
    parts: list[str] = []
    if years > 0:
        parts.append(f"{years} Jahr{'en' if years != 1 else ''}")
    if months > 0:
        parts.append(f"{months} Monat{'en' if months != 1 else ''}")
    if not parts:
        parts.append(f"{days} Tag{'en' if days != 1 else ''}")
    return ", ".join(parts)


def get_bot_info() -> dict[str, Any]:
    """Return a dict describing the live bot, suitable for injecting into
    template context or returning from a JSON endpoint.

    Always returns a populated dict; missing pieces fall back to defaults so
    templates never see ``None``.
    """
    bot = _BOT
    # Prefer the live active-ping measurement; fall back to the passive
    # gateway heartbeat latency if the monitor hasn't produced a sample yet.
    ping = get_ping_ms()
    latency_ms = ping if ping is not None else (round(bot.latency * 1000, 1) if bot.latency else 0.0)

    if bot is None or bot.user is None:
        return {
            "name": "CogniX",
            "username": "CogniX",
            "id": 0,
            "avatar_url": "",
            "online": False,
            "uptime": "\u2014",
            "uptime_seconds": 0,
            "latency_ms": latency_ms,
            "guild_count": 0,
            "user_count": 0,
            "version": "0.1.0",
            "created_at": "",
            "age_text": "",
            "footer": "\u00a9 2026 VeridonNetzwerk \u00b7 MIT License \u00b7 Built with AI \U0001F916",
            "error": _BOT_ERROR,
            "ping_error": _PING_ERROR,
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
        "latency_ms": latency_ms,
        "guild_count": len(bot.guilds),
        "user_count": user_count,
        "version": "0.1.0",
        "created_at": bot.user.created_at.strftime("%d. %b. %Y"),
        "age_text": _format_age(bot.user.created_at),
        "id": bot.user.id,
        "footer": "\u00a9 2026 VeridonNetzwerk \u00b7 MIT License \u00b7 Built with AI \U0001F916",
        "error": _BOT_ERROR,
        "ping_error": _PING_ERROR,
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
    3. SystemConfig.enabled_cogs for this server includes the cog name

    Defaults to ``True`` when no DB data exists. Falls back to ``True`` on any DB
    error so a misconfigured DB doesn't silently brick all commands.
    """
    key = (server_id, cog_name)
    now = time.time()
    cached = _COG_STATE_CACHE.get(key)
    if cached is not None and (now - cached[1]) < _COG_STATE_TTL:
        return cached[0]

    # Check 1: Is the cog actually loaded globally?
    from bot.cogs.registry import get_cog_info, get_loaded_cogs

    loaded = set(get_loaded_cogs())
    if _BOT is not None:
        loaded |= set(_BOT.extensions.keys())

    info = get_cog_info(cog_name)
    if info is not None:
        if info["module"] not in loaded:
            _COG_STATE_CACHE[key] = (False, now)
            return False
    elif cog_name not in loaded:
        _COG_STATE_CACHE[key] = (False, now)
        return False

    try:
        from sqlalchemy import select  # local import to avoid cycle at boot

        from bot.database.models.server.server_config import ServerConfig
        from bot.database.session import db_session

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
