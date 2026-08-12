"""Cog Registry — central registry of all available cogs and their load state.

This module provides:
1. A static list of built-in cogs with metadata (name, description, category)
2. Dynamic discovery of marketplace-installed cogs from the database
3. Runtime tracking of which cogs are currently loaded
4. Helper functions to load/unload/reload cogs with automatic slash-command tree sync
5. Persistence of loaded state to the database so it survives restarts

Design principle:
- Extensions in discord.py are bot-wide (not per-guild). When a cog is loaded,
  its commands become available on ALL servers.
- Per-server enable/disable is handled separately via ServerConfig.enabled_cogs.
- This registry tracks which cogs are *loaded* globally.
- Built-in cogs are defined statically; marketplace-cogs are discovered dynamically.
"""

from __future__ import annotations

import asyncio
from typing import Any

from config.logging import get_logger

log = get_logger("bot.cog_registry")

# ---------------------------------------------------------------------------
# Built-in Cogs Registry — defines cogs bundled with the bot source
# ---------------------------------------------------------------------------

CogInfo = dict[str, str | bool]  # {module: ..., name: ..., description: ..., category: ...}

BUILTIN_COGS: list[CogInfo] = [
    {
        "module": "bot.cogs.moderation",
        "name": "Moderation",
        "description": "Ban, kick, mute, warn, purge commands for server moderation",
        "category": "Moderation",
        "requires_admin": True,
    },
    {
        "module": "bot.cogs.utility",
        "name": "Utility",
        "description": "Ping, info, userinfo, serverinfo, roll, flip utility commands",
        "category": "Utility",
        "requires_admin": False,
    },
    {
        "module": "bot.cogs.tickets",
        "name": "Tickets",
        "description": "Thread-based support tickets with transcript export",
        "category": "Support",
        "requires_admin": True,
    },
    {
        "module": "bot.cogs.stats",
        "name": "Stats",
        "description": "Message and command statistics tracking",
        "category": "Analytics",
        "requires_admin": False,
    },
    {
        "module": "bot.cogs.backups",
        "name": "Backups",
        "description": "Backup and restore server roles, channels, and permissions",
        "category": "Administration",
        "requires_admin": True,
    },
    {
        "module": "bot.cogs.music",
        "name": "Music",
        "description": "Music playback with playlists (requires yt-dlp)",
        "category": "Fun",
        "requires_admin": True,
    },
    {
        "module": "bot.cogs.activity_log",
        "name": "Activity Log",
        "description": "Logs all Discord events (messages, members, channels, etc.)",
        "category": "Logging",
        "requires_admin": False,
    },
    {
        "module": "bot.cogs.giveaway",
        "name": "Giveaways",
        "description": "Time-limited giveaways with reaction-based entries",
        "category": "Fun",
        "requires_admin": True,
    },
    {
        "module": "bot.cogs.welcome",
        "name": "Welcome/Leave",
        "description": "Custom embed messages on member join, leave, and boost",
        "category": "Utility",
        "requires_admin": False,
    },
    {
        "module": "bot.cogs.invite_tracker",
        "name": "Invite Tracker",
        "description": "Track who invited whom with invite statistics",
        "category": "Analytics",
        "requires_admin": False,
    },
]

# ---------------------------------------------------------------------------
# Dynamic Available Cogs — built-in + marketplace packages merged together
# ---------------------------------------------------------------------------


def get_all_cog_info() -> list[CogInfo]:
    """Return metadata for all available cogs (built-in + marketplace)."""
    result = [dict(c) for c in BUILTIN_COGS]

    # Merge installed marketplace packages that haven't been uninstalled
    try:
        sync_result = _get_installed_marketplace_cogs()
    except Exception:  # noqa: BLE001
        return result

    for pkg in sync_result:
        module_name = pkg.module_name or f"bot.cogs.ext_{pkg.name.lower().replace(' ', '_')}"
        already = any(c["module"] == module_name for c in result)
        if not already:
            result.append({
                "module": module_name,
                "name": pkg.display_name or pkg.name,
                "description": pkg.description or f"Installed marketplace cog",
                "category": pkg.category or "Marketplace",
                "requires_admin": pkg.requires_admin,
            })

    return result


def _get_installed_marketplace_cogs() -> list[Any]:
    """Sync helper to get installed marketplace packages."""
    try:
        from database.models.cog_package import CogPackage
        from database.session import db_session
        from sqlalchemy import select as sa_select

        async def _load():
            async with db_session() as s:
                return list(await s.scalars(
                    sa_select(CogPackage).where(
                        CogPackage.installed.is_(True),
                        CogPackage.uninstall_requested.is_(False),
                    )
                ))
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop is not None and loop.is_running():
            fut = asyncio.run_coroutine_threadsafe(_load(), loop)
            return fut.result(timeout=2.0)
        return []
    except Exception:  # noqa: BLE001
        return []


# Alias for backwards compatibility with existing imports
AVAILABLE_COGS = BUILTIN_COGS  # type: ignore[name-defined]


# ---------------------------------------------------------------------------
# Runtime state — which cogs are currently loaded
# ---------------------------------------------------------------------------

_loaded_cogs: set[str] = set()  # Fully qualified extension names


def get_loaded_cogs() -> list[str]:
    """Return list of fully qualified extension names that are currently loaded."""
    return sorted(_loaded_cogs)


def is_cog_loaded(module_name: str) -> bool:
    """Check if a specific cog module is currently loaded."""
    # Accept both short names (moderation) and full names (bot.cogs.moderation)
    full = module_name if module_name.startswith("bot.") else f"bot.cogs.{module_name}"
    return full in _loaded_cogs


def get_cog_info(name: str) -> CogInfo | None:
    """Get metadata for a cog by name or module path."""
    all_info = get_all_cog_info()
    for info in all_info:
        if info["module"] == name:
            return info
        if info["name"].lower() == name.lower():
            return info
        # Check short name match (e.g. "moderation" → "Moderation")
        normalized_info = info["name"].lower().replace(" ", "_").replace("/", "_")
        normalized_name = name.lower().replace(" ", "_").replace("/", "_")
        if normalized_info == normalized_name:
            return info
    return None


def _update_loaded_state(module_name: str, loaded: bool) -> None:
    """Update the internal tracking of loaded cogs."""
    if loaded:
        _loaded_cogs.add(module_name)
    else:
        _loaded_cogs.discard(module_name)


# ---------------------------------------------------------------------------
# Load/Unload helpers — used by IPC, admin commands, and marketplace
# ---------------------------------------------------------------------------


async def load_cog(bot: Any, cog_name: str) -> dict[str, Any]:
    """Load a single cog by name or module path.

    Returns: {"ok": True} or {"error": "..."}
    """
    info = get_cog_info(cog_name)
    if info is None:
        return {"error": f"Unknown cog: {cog_name}"}

    module_name = info["module"]

    if module_name in _loaded_cogs:
        return {"error": f"Cog already loaded: {info['name']}"}

    try:
        await bot.load_extension(module_name)
        _update_loaded_state(module_name, True)
        await bot.tree.sync()
        log.info("cog_loaded", cog=info["name"], module=module_name)
        return {"ok": True, "cog": info["name"], "loaded_by": "dynamic"}
    except Exception as exc:  # noqa: BLE001
        log.error("cog_load_failed", cog=cog_name, error=str(exc))
        return {"error": f"Failed to load cog '{cog_name}': {exc}"}


async def unload_cog(bot: Any, cog_name: str) -> dict[str, Any]:
    """Unload a single cog by name or module path.

    Returns: {"ok": True} or {"error": "..."}
    """
    info = get_cog_info(cog_name)
    if info is None:
        return {"error": f"Unknown cog: {cog_name}"}

    module_name = info["module"]

    if module_name not in _loaded_cogs:
        return {"error": f"Cog not loaded: {info['name']}"}

    try:
        await bot.unload_extension(module_name)
        _update_loaded_state(module_name, False)
        await bot.tree.sync()
        log.info("cog_unloaded", cog=info["name"], module=module_name)
        return {"ok": True, "cog": info["name"]}
    except Exception as exc:  # noqa: BLE001
        log.error("cog_unload_failed", cog=cog_name, error=str(exc))
        return {"error": f"Failed to unload cog '{cog_name}': {exc}"}


async def reload_cog(bot: Any, cog_name: str) -> dict[str, Any]:
    """Reload a single cog by name or module path.

    Returns: {"ok": True} or {"error": "..."}
    """
    info = get_cog_info(cog_name)
    if info is None:
        return {"error": f"Unknown cog: {cog_name}"}

    module_name = info["module"]

    unload_result = await unload_cog(bot, cog_name)
    if not unload_result.get("ok"):
        return {"error": f"Unload failed: {unload_result.get('error', '')}"}

    try:
        await bot.reload_extension(module_name)
        _update_loaded_state(module_name, True)
        await bot.tree.sync()
        log.info("cog_reloaded", cog=info["name"], module=module_name)
        return {"ok": True, "cog": info["name"]}
    except Exception as exc:  # noqa: BLE001
        log.error("cog_reload_failed", cog=cog_name, error=str(exc))
        # Try to reload it back in case reload_extension failed
        try:
            await bot.load_extension(module_name)
            _update_loaded_state(module_name, True)
            await bot.tree.sync()
        except Exception:  # noqa: BLE001
            pass
        return {"error": f"Failed to reload cog '{cog_name}': {exc}"}


# ---------------------------------------------------------------------------
# Persistence helpers — save/load which cogs should be loaded after restart
# ---------------------------------------------------------------------------

_LOADED_COGS_KEY = "loaded_cogs_v2"


def get_persisted_loaded_cogs() -> list[str]:
    """Get the list of cogs that SHOULD be loaded (from DB)."""
    try:
        from database.session import db_session
        from database.models.system_config import SystemConfig
        from sqlalchemy import select as sa_select

        async def _load():
            async with db_session() as s:
                cfg = await s.scalar(
                    sa_select(SystemConfig).where(SystemConfig.id == 1)
                )
                if cfg and hasattr(cfg, "loaded_cogs_v2") and cfg.loaded_cogs_v2:
                    return list(cfg.loaded_cogs_v2)
            return []

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop is not None and loop.is_running():
            fut = asyncio.run_coroutine_threadsafe(_load(), loop)
            return fut.result(timeout=2.0)
        return []
    except Exception:  # noqa: BLE001
        return []


def persist_loaded_cogs(cog_names: list[str]) -> None:
    """Save the list of loaded cogs to system_config for persistence across restarts."""
    try:
        from database.session import db_session
        from sqlalchemy import select as sa_select

        async def _persist():
            async with db_session() as s:
                from database.models.system_config import SystemConfig

                cfg = await s.scalar(sa_select(SystemConfig).where(SystemConfig.id == 1))
                if cfg is not None:
                    cfg.loaded_cogs_v2 = list(cog_names)
                    await s.flush()

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop is not None and loop.is_running():
            fut = asyncio.run_coroutine_threadsafe(_persist(), loop)
            fut.result(timeout=2.0)
    except Exception as exc:  # noqa: BLE001
        log.warning("persist_loaded_cogs_failed", error=str(exc))


async def restore_loaded_cogs(bot: Any) -> int:
    """Restore previously saved cog load state.

    Returns the number of cogs that were re-loaded.
    """
    saved = get_persisted_loaded_cogs()
    if not saved:
        return 0

    count = 0
    for name in saved:
        result = await load_cog(bot, name)
        if result.get("ok"):
            count += 1
        else:
            log.warning("restore_cog_failed", cog=name, error=result.get("error"))

    if count > 0:
        persist_loaded_cogs(get_loaded_cogs())

    return count
