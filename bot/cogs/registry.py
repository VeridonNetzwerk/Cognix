"""Cog Registry — central registry of all available cogs and their load state.

This module provides:
1. Dynamic discovery of cogs from the top-level cogs/ directory
2. Runtime tracking of which cogs are currently loaded
3. Helper functions to load/unload/reload cogs with automatic slash-command tree sync
4. Persistence of loaded state to the database so it survives restarts

Design principle:
- Extensions in discord.py are bot-wide (not per-guild). When a cog is loaded,
  its commands become available on ALL servers.
- Per-server enable/disable is handled separately via ServerConfig.enabled_cogs.
- This registry tracks which cogs are *loaded* globally.
- Cogs live in the top-level cogs/ directory and are discovered dynamically.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from bot.config.logging import get_logger

log = get_logger("bot.cog_registry")

# ---------------------------------------------------------------------------
# Cog Discovery — scan the top-level cogs/ directory for cog modules
# ---------------------------------------------------------------------------

CogInfo = dict[str, str | bool]

_COGS_DIR = Path(__file__).resolve().parent.parent.parent / "cogs"


def _make_cog_info(module: str, *, name: str = "", description: str = "", category: str = "", requires_admin: bool = False) -> CogInfo:
    """Build a CogInfo dict, deriving name from module if not provided."""
    if not name:
        short = module.rsplit(".", 1)[-1]
        name = short.replace("_", " ").title()
    return {
        "module": module,
        "name": name,
        "description": description,
        "category": category,
        "requires_admin": requires_admin,
    }


def _discover_cogs() -> list[CogInfo]:
    """Discover all cog modules in the top-level cogs/ directory.

    Scans for .py files (excluding __init__.py, _*.py) in cogs/
    and its subdirectories. Each module may define a COG_INFO dict with
    metadata (name, description, category, requires_admin).
    """
    import importlib

    if not _COGS_DIR.exists():
        return []

    cogs: list[CogInfo] = []

    for py_file in sorted(_COGS_DIR.rglob("*.py")):
        if py_file.name == "__init__.py" or py_file.name.startswith("_"):
            continue

        try:
            rel = py_file.relative_to(_COGS_DIR.parent)
            module_parts = list(rel.parts)
            module_parts[-1] = module_parts[-1].removesuffix(".py")
            module_name = ".".join(module_parts)
        except ValueError:
            continue

        try:
            mod = importlib.import_module(module_name)
            info = getattr(mod, "COG_INFO", None)
            if info and isinstance(info, dict):
                cogs.append(_make_cog_info(
                    module_name,
                    name=info.get("name", ""),
                    description=info.get("description", ""),
                    category=info.get("category", ""),
                    requires_admin=info.get("requires_admin", False),
                ))
            else:
                cogs.append(_make_cog_info(module_name))
        except Exception as exc:  # noqa: BLE001
            log.warning("cog_discover_failed", module=module_name, error=str(exc))
            cogs.append(_make_cog_info(module_name))

    return cogs


def _discover_cogs_cached() -> list[CogInfo]:
    """Discover cogs with caching to avoid repeated filesystem scans."""
    global _cogs_cache
    if _cogs_cache is not None:
        return _cogs_cache
    _cogs_cache = _discover_cogs()
    return _cogs_cache


_cogs_cache: list[CogInfo] | None = None


def refresh_cogs_cache() -> None:
    """Force a re-scan of the cogs directory. Call after installing/removing cogs."""
    global _cogs_cache
    _cogs_cache = None


def get_all_cog_info() -> list[CogInfo]:
    """Return metadata for all available cogs."""
    return [dict(c) for c in _discover_cogs_cached()]


# ---------------------------------------------------------------------------
# Runtime state — which cogs are currently loaded
# ---------------------------------------------------------------------------

_loaded_cogs: set[str] = set()  # Fully qualified extension names


def get_loaded_cogs() -> list[str]:
    """Return list of fully qualified extension names that are currently loaded."""
    return sorted(_loaded_cogs)


def is_cog_loaded(module_name: str) -> bool:
    """Check if a specific cog module is currently loaded."""
    if module_name.startswith("cogs.") or module_name.startswith("bot."):
        return module_name in _loaded_cogs
    info = get_cog_info(module_name)
    if info:
        return info["module"] in _loaded_cogs
    return False


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


# ---------------------------------------------------------------------------
# Widget discovery — collect WIDGETS from loaded cog modules
# ---------------------------------------------------------------------------

WidgetInfo = dict[str, str]


def get_available_widgets() -> list[WidgetInfo]:
    """Discover widgets from all loaded cog modules.

    Each cog module may define a ``WIDGETS`` list of dicts:
        {"id": "moderation_recent", "title": "Recent Actions",
         "template": "widgets/moderation_recent.html", "size": "medium"}
    """
    import importlib

    widgets: list[WidgetInfo] = []
    for module_name in sorted(_loaded_cogs):
        try:
            mod = importlib.import_module(module_name)
            cog_widgets = getattr(mod, "WIDGETS", None)
            if cog_widgets and isinstance(cog_widgets, list):
                for w in cog_widgets:
                    if isinstance(w, dict) and "id" in w and "template" in w:
                        w_copy = dict(w)
                        w_copy.setdefault("cog", module_name)
                        w_copy.setdefault("size", "medium")
                        widgets.append(w_copy)
        except Exception as exc:  # noqa: BLE001
            log.warning("widget_discover_failed", module=module_name, error=str(exc))

    # Also check bot.extensions for live-loaded cogs
    return widgets


def _update_loaded_state(module_name: str, loaded: bool) -> None:
    """Update the internal tracking of loaded cogs."""
    if loaded:
        _loaded_cogs.add(module_name)
    else:
        _loaded_cogs.discard(module_name)


# ---------------------------------------------------------------------------
# Load/Unload helpers — used by IPC, admin commands, and web API
# ---------------------------------------------------------------------------


async def _sync_commands_to_guilds(bot: Any) -> None:
    """Sync slash commands to every guild the bot is in.

    Guild commands propagate instantly (unlike global commands which Discord
    caches for up to 1h). We sync globally first (to remove stale global
    commands) then copy the tree to each guild for instant propagation.
    """
    try:
        # Sync globally — this removes any global commands that are no longer
        # in the tree (e.g. from an unloaded cog). Discord caches these for
        # up to 1h, but at least new clients won't see them.
        await bot.tree.sync()
        # Sync to each guild for instant propagation
        for guild in bot.guilds:
            try:
                await bot.tree.sync(guild=guild)
            except Exception as exc:  # noqa: BLE001
                log.warning("guild_sync_failed", guild=guild.id, error=str(exc))
    except Exception as exc:  # noqa: BLE001
        log.warning("command_sync_failed", error=str(exc))


def _resolve_cog(cog_name: str) -> tuple[CogInfo | None, str]:
    """Resolve a cog name or module path to (info, module_name)."""
    if cog_name.startswith("cogs.") or cog_name.startswith("bot."):
        return get_cog_info(cog_name), cog_name
    info = get_cog_info(cog_name)
    if info is None:
        return None, cog_name
    return info, info["module"]


def _invalidate_cache(cog_name: str) -> None:
    """Invalidate cog state cache after load/unload."""
    try:
        from bot.runtime import invalidate_cog_state_cache
        invalidate_cog_state_cache(cog_name=cog_name.lower())
    except Exception:  # noqa: BLE001
        pass


async def load_cog(bot: Any, cog_name: str) -> dict[str, Any]:
    """Load a single cog by name or module path.

    Returns: {"ok": True} or {"error": "..."}
    """
    info, module_name = _resolve_cog(cog_name)
    if info is None:
        return {"error": f"Unknown cog: {cog_name}"}

    if module_name in _loaded_cogs:
        return {"error": f"Cog already loaded: {info['name']}"}

    try:
        await bot.load_extension(module_name)
        _update_loaded_state(module_name, True)
        _invalidate_cache(info["name"])
        await _sync_commands_to_guilds(bot)
        log.info("cog_loaded", cog=info["name"], module=module_name)
        return {"ok": True, "cog": info["name"], "loaded_by": "dynamic"}
    except Exception as exc:  # noqa: BLE001
        log.error("cog_load_failed", cog=cog_name, error=str(exc))
        return {"error": f"Failed to load cog '{cog_name}': {exc}"}


async def unload_cog(bot: Any, cog_name: str) -> dict[str, Any]:
    """Unload a single cog by name or module path.

    Returns: {"ok": True} or {"error": "..."}
    """
    info, module_name = _resolve_cog(cog_name)
    if info is None:
        return {"error": f"Unknown cog: {cog_name}"}

    if module_name not in _loaded_cogs:
        return {"error": f"Cog not loaded: {info['name']}"}

    try:
        await bot.unload_extension(module_name)
        _update_loaded_state(module_name, False)
        _invalidate_cache(info["name"])
        await _sync_commands_to_guilds(bot)
        log.info("cog_unloaded", cog=info["name"], module=module_name)
        return {"ok": True, "cog": info["name"]}
    except Exception as exc:  # noqa: BLE001
        log.error("cog_unload_failed", cog=cog_name, error=str(exc))
        return {"error": f"Failed to unload cog '{cog_name}': {exc}"}


async def reload_cog(bot: Any, cog_name: str) -> dict[str, Any]:
    """Reload a single cog by name or module path.

    Returns: {"ok": True} or {"error": "..."}
    """
    info, module_name = _resolve_cog(cog_name)
    if info is None:
        return {"error": f"Unknown cog: {cog_name}"}

    unload_result = await unload_cog(bot, cog_name)
    if not unload_result.get("ok"):
        return {"error": f"Unload failed: {unload_result.get('error', '')}"}

    try:
        await bot.load_extension(module_name)
        _update_loaded_state(module_name, True)
        await _sync_commands_to_guilds(bot)
        log.info("cog_reloaded", cog=info["name"], module=module_name)
        return {"ok": True, "cog": info["name"]}
    except Exception as exc:  # noqa: BLE001
        log.error("cog_reload_failed", cog=cog_name, error=str(exc))
        return {"error": f"Failed to reload cog '{cog_name}': {exc}"}


# ---------------------------------------------------------------------------
# Persistence helpers — save/load which cogs should be loaded after restart
# ---------------------------------------------------------------------------

async def get_persisted_loaded_cogs() -> list[str]:
    """Get the list of cogs that SHOULD be loaded (from DB)."""
    try:
        from bot.database.session import db_session
        from bot.database.models.system.system_config import SystemConfig
        from sqlalchemy import select as sa_select

        async with db_session() as s:
            cfg = await s.scalar(
                sa_select(SystemConfig).where(SystemConfig.id == 1)
            )
            if cfg and hasattr(cfg, "loaded_cogs_v2") and cfg.loaded_cogs_v2:
                return list(cfg.loaded_cogs_v2)
        return []
    except Exception:  # noqa: BLE001
        return []


async def persist_loaded_cogs(cog_names: list[str]) -> None:
    """Save the list of loaded cogs to system_config for persistence across restarts."""
    try:
        from bot.database.session import db_session
        from sqlalchemy import select as sa_select

        async with db_session() as s:
            from bot.database.models.system.system_config import SystemConfig

            cfg = await s.scalar(sa_select(SystemConfig).where(SystemConfig.id == 1))
            if cfg is not None:
                cfg.loaded_cogs_v2 = list(cog_names)
                await s.flush()
    except Exception as exc:  # noqa: BLE001
        log.warning("persist_loaded_cogs_failed", error=str(exc))


async def restore_loaded_cogs(bot: Any) -> int:
    """Restore previously saved cog load state.

    Returns the number of cogs that were re-loaded.
    """
    saved = await get_persisted_loaded_cogs()
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
        await persist_loaded_cogs(get_loaded_cogs())

    return count
