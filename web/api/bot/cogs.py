"""Cog control routes — global load state and per-server enable/disable."""

from __future__ import annotations

import asyncio
import json
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select

from bot.cogs.registry import (
    get_all_cog_info,
    get_store_cog_info,
    get_cog_updates,
    install_cog,
    uninstall_cog,
    load_cog,
    unload_cog,
    reload_cog,
    get_cog_requirements,
    get_cog_files,
    refresh_cogs_cache,
    refresh_store_cache,
    is_cog_loaded,
    _COGS_DIR,
    _refresh_template_loader,
    _pip_install,
    _parse_requirements,
    _load_pkg_tracking,
    _save_pkg_tracking,
)
from bot.cogs import github_store
from bot.database.models.server.server_config import ServerConfig
from bot.runtime import get_bot, invalidate_cog_state_cache
from web.deps import SessionDep, require_admin
from web.services.bot_ipc import get_ipc

router = APIRouter(prefix="/cogs", tags=["cogs"], dependencies=[Depends(require_admin)])


def _warnings_result(warnings: list[str]) -> dict[str, Any]:
    """Build a result dict, including warnings if present."""
    if warnings:
        return {"ok": True, "warning": "; ".join(warnings)}
    return {"ok": True}


class CogActionRequest(BaseModel):
    action: Literal["load", "unload", "reload"]


class ServerCogEnableRequest(BaseModel):
    cog_name: str
    enabled: bool


class CogInstallRequest(BaseModel):
    module: str


class CogDevInstallRequest(BaseModel):
    path: str
    module: str | None = None


# ---------------------------------------------------------------------------
# Cog Store — list available, install, uninstall
# ---------------------------------------------------------------------------


@router.get("/store")
async def list_store_cogs() -> dict:
    """Return all cogs available in the store (not yet installed)."""
    # Pull the store catalog from GitHub (cached) if no local cogs_store exists.
    ok = await github_store.ensure_store_cache()
    refresh_store_cache()
    store_cogs = get_store_cog_info()
    installed_cogs = get_all_cog_info()
    installed_modules = {c["module"] for c in installed_cogs}

    return {
        "cogs": [
            {
                "name": info["name"],
                "module": info["module"],
                "description": info.get("description", ""),
                "category": info.get("category", ""),
                "requires_admin": info.get("requires_admin", False),
                "version": info.get("version", ""),
                "installed": info["module"] in installed_modules,
                "requirements": get_cog_requirements(info["module"]),
                "extra_files": get_cog_files(info["module"]),
                "verified": info.get("verified", False),
                "permissions": info.get("permissions", []),
            }
            for info in store_cogs
        ],
        "total": len(store_cogs),
        "store_available": ok,
        "sync": github_store.get_sync_status(),
    }


@router.get("/store/updates")
async def list_cog_updates() -> dict:
    """Return installed cogs that have a newer version available in the store."""
    updates = get_cog_updates()
    return {"updates": updates, "total": len(updates)}


@router.post("/store/refresh")
async def store_refresh() -> dict:
    """Force re-pull the cog store catalog from GitHub."""
    ok = await github_store.ensure_store_cache(force=True)
    refresh_store_cache()
    return {"ok": ok, "total": len(get_store_cog_info()), "sync": github_store.get_sync_status()}


@router.post("/store/update")
async def store_update_cog(req: CogInstallRequest) -> dict:
    """Update an installed cog — re-install from store (overwrites installed copy)."""
    await github_store.ensure_store_cache()
    result = await asyncio.to_thread(install_cog, req.module)
    if not result.get("ok"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, result.get("error", "update failed"))

    warnings = []
    if result.get("warning"):
        warnings.append(result["warning"])

    bot = get_bot()
    if bot is not None and is_cog_loaded(req.module):
        reload_result = await reload_cog(bot, req.module)
        if not reload_result.get("ok"):
            warnings.append(f"Reload failed: {reload_result.get('error')}")

    return _warnings_result(warnings)


@router.post("/store/install")
async def store_install_cog(req: CogInstallRequest) -> dict:
    """Install a cog from the store into cogs/ and load it."""
    await github_store.ensure_store_cache()
    result = await asyncio.to_thread(install_cog, req.module)
    if not result.get("ok"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, result.get("error", "install failed"))

    warnings = []
    if result.get("warning"):
        warnings.append(result["warning"])

    bot = get_bot()
    if bot is not None:
        load_result = await load_cog(bot, req.module)
        if not load_result.get("ok"):
            warnings.append(f"Load failed: {load_result.get('error')}")

    return _warnings_result(warnings)


@router.post("/store/uninstall")
async def store_uninstall_cog(req: CogInstallRequest) -> dict:
    """Uninstall a cog — unload it and remove from cogs/."""
    bot = get_bot()
    if bot is not None and is_cog_loaded(req.module):
        unload_result = await unload_cog(bot, req.module)
        if not unload_result.get("ok"):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Failed to unload: {unload_result.get('error')}")

    result = uninstall_cog(req.module)
    if not result.get("ok"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, result.get("error", "uninstall failed"))

    return _warnings_result([result["warning"]] if result.get("warning") else [])


@router.post("/store/dev-install")
async def store_dev_install_cog(req: CogDevInstallRequest) -> dict:
    """Install a cog from a local filesystem path (developer mode).

    Copies the cog directory from the given path into cogs/, installs pip
    requirements if present, and optionally loads it. The module name is
    derived from the directory name if not provided.
    """
    import shutil
    from pathlib import Path

    src_path = Path(req.path).resolve()
    if not src_path.exists():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Path does not exist: {src_path}")
    if not src_path.is_dir():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Path must be a directory")

    # Derive module name from directory name if not provided
    cog_name = req.module or src_path.name
    module_name = f"cogs.{cog_name}.{cog_name}"

    # Find the .py file in the source directory
    py_files = [f for f in src_path.iterdir() if f.suffix == ".py" and f.name != "__init__.py" and not f.name.startswith("_")]
    if not py_files:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No cog .py file found in the given path")

    # Target directory in cogs/
    target_dir = _COGS_DIR / src_path.name
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir.parent / "__init__.py").write_text("", encoding="utf-8")
    if not (target_dir / "__init__.py").exists():
        (target_dir / "__init__.py").write_text("", encoding="utf-8")

    # Copy files
    for item in src_path.iterdir():
        if item.name == "__pycache__":
            continue
        dest = target_dir / item.name
        if item.is_dir():
            shutil.copytree(str(item), str(dest), dirs_exist_ok=True)
        else:
            shutil.copy2(str(item), str(dest))

    # Install pip requirements if present
    req_file = src_path / "requirements.txt"
    if req_file.exists():
        packages = _parse_requirements(req_file)
        if packages:
            pip_result = _pip_install(packages)
            tracking = _load_pkg_tracking()
            tracking[module_name] = packages
            _save_pkg_tracking(tracking)
            if not pip_result.get("ok"):
                pass  # Don't fail — cog files are copied

    # Refresh caches
    refresh_cogs_cache()
    refresh_store_cache()
    _refresh_template_loader()

    bot = get_bot()
    warnings: list[str] = []
    if bot is not None:
        load_result = await load_cog(bot, module_name)
        if not load_result.get("ok"):
            warnings.append(f"Load failed: {load_result.get('error')}")

    result: dict[str, Any] = {"ok": True, "module": module_name}
    if warnings:
        result["warning"] = "; ".join(warnings)
    return result


# ---------------------------------------------------------------------------
# SSE streaming install/uninstall with real progress
# ---------------------------------------------------------------------------


def _sse_event(event: str, data: dict[str, Any]) -> str:
    """Format a Server-Sent Event."""
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


@router.post("/store/install-stream")
async def store_install_cog_stream(req: CogInstallRequest):
    """Install a cog with SSE progress updates."""
    async def generate():
        yield _sse_event("progress", {"percent": 5, "step": "Starting installation…"})
        await asyncio.sleep(0.1)

        # Step 1: Copy files (run in thread to avoid blocking event loop)
        yield _sse_event("progress", {"percent": 15, "step": "Copying cog files…"})
        await github_store.ensure_store_cache()
        yield _sse_event("progress", {"percent": 25, "step": "Extracting and validating cog…"})
        result = await asyncio.to_thread(install_cog, req.module)
        if not result.get("ok"):
            yield _sse_event("error", {"detail": result.get("error", "install failed")})
            return
        yield _sse_event("progress", {"percent": 60, "step": "Files copied successfully"})
        await asyncio.sleep(0.1)

        warnings = []
        if result.get("warning"):
            warnings.append(result["warning"])
            yield _sse_event("progress", {"percent": 70, "step": f"Warning: {result['warning']}"})

        # Step 2: Load the cog
        yield _sse_event("progress", {"percent": 75, "step": "Loading cog into bot…"})
        bot = get_bot()
        if bot is not None:
            load_result = await load_cog(bot, req.module)
            if not load_result.get("ok"):
                warnings.append(f"Load failed: {load_result.get('error')}")
                yield _sse_event("progress", {"percent": 85, "step": f"Load failed: {load_result.get('error')}", "warning": True})
            else:
                yield _sse_event("progress", {"percent": 90, "step": "Cog loaded successfully"})
        await asyncio.sleep(0.1)

        # Done
        yield _sse_event("progress", {"percent": 100, "step": "Installation complete"})
        done_data = {"ok": True}
        if warnings:
            done_data["warning"] = "; ".join(warnings)
        yield _sse_event("done", done_data)

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.post("/store/uninstall-stream")
async def store_uninstall_cog_stream(req: CogInstallRequest):
    """Uninstall a cog with SSE progress updates."""
    async def generate():
        yield _sse_event("progress", {"percent": 5, "step": "Starting uninstall…"})
        await asyncio.sleep(0.1)

        # Step 1: Unload if loaded
        bot = get_bot()
        if bot is not None and is_cog_loaded(req.module):
            yield _sse_event("progress", {"percent": 20, "step": "Unloading cog…"})
            unload_result = await unload_cog(bot, req.module)
            if not unload_result.get("ok"):
                yield _sse_event("error", {"detail": f"Failed to unload: {unload_result.get('error')}"})
                return
            yield _sse_event("progress", {"percent": 40, "step": "Cog unloaded"})
        else:
            yield _sse_event("progress", {"percent": 30, "step": "Cog not loaded, skipping unload"})
        await asyncio.sleep(0.1)

        # Step 2: Remove files
        yield _sse_event("progress", {"percent": 55, "step": "Removing cog files…"})
        result = uninstall_cog(req.module)
        if not result.get("ok"):
            yield _sse_event("error", {"detail": result.get("error", "uninstall failed")})
            return
        yield _sse_event("progress", {"percent": 90, "step": "Files removed"})
        await asyncio.sleep(0.1)

        # Done
        warning = result.get("warning")
        yield _sse_event("progress", {"percent": 100, "step": "Uninstall complete"})
        done_data = {"ok": True}
        if warning:
            done_data["warning"] = warning
        yield _sse_event("done", done_data)

    return StreamingResponse(generate(), media_type="text/event-stream")


# ---------------------------------------------------------------------------
# Global load state (what cogs are currently loaded on the bot)
# ---------------------------------------------------------------------------


@router.get("/")
async def list_cogs(session: SessionDep) -> dict:
    """Return all available cogs with their global load status."""
    from bot.pages._shared import _get_loaded_cogs_set

    all_cogs = get_all_cog_info()
    loaded_set = _get_loaded_cogs_set()

    return {
        "cogs": [
            {
                "name": info["name"],
                "module": info["module"],
                "description": info.get("description", ""),
                "category": info.get("category", ""),
                "loaded": info["module"] in loaded_set,
                "requires_admin": info.get("requires_admin", False),
                "version": info.get("version", ""),
            }
            for info in all_cogs
        ],
        "total": len(all_cogs),
        "loaded_count": sum(1 for c in all_cogs if c["module"] in loaded_set),
    }


# ---------------------------------------------------------------------------
# Standard cog actions (load/unload/reload via IPC)
# ---------------------------------------------------------------------------


@router.post("/{cog_name}")
async def cog_action(cog_name: str, req: CogActionRequest) -> dict:
    """Load/unload/reload a cog globally (affects all servers)."""
    return await _apply_cog_action(cog_name, req.action)


# ---------------------------------------------------------------------------
# Named cog actions (JSON) — drive the dashboard's fetch + toast UX so that
# failures surface as visible error toasts instead of raw error pages.
# ---------------------------------------------------------------------------


async def _apply_cog_action(cog_name: str, action: str) -> dict:
    """Load/unload/reload a cog via the in-process bot, or IPC as fallback."""
    actions = {"load": load_cog, "unload": unload_cog, "reload": reload_cog}
    if action not in actions:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"unknown action: {action}")
    bot = get_bot()
    if bot is not None:
        result = await actions[action](bot, cog_name)
        if not result.get("ok"):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, result.get("error", "failed"))
        return {"ok": True}
    ipc = get_ipc()
    try:
        res = await ipc.call(f"cog.{action}", {"name": cog_name}, timeout=5.0)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "bot offline") from exc
    if res.get("status") != "ok":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, res.get("error", "failed"))
    return {"ok": True}


@router.post("/{cog_name}/load")
async def api_cog_load(cog_name: str) -> dict:
    return await _apply_cog_action(cog_name, "load")


@router.post("/{cog_name}/unload")
async def api_cog_unload(cog_name: str) -> dict:
    return await _apply_cog_action(cog_name, "unload")


@router.post("/{cog_name}/reload")
async def api_cog_reload(cog_name: str) -> dict:
    return await _apply_cog_action(cog_name, "reload")


@router.post("/{cog_name}/toggle")
async def api_cog_global_toggle(cog_name: str, session: SessionDep) -> dict:
    """Enable/disable a cog globally (server_id=None CogState row)."""
    from bot.database.models.cogs.cog_state import CogState

    cog_name_lower = cog_name.lower()
    row = await session.scalar(
        select(CogState).where(CogState.server_id.is_(None), CogState.cog_name == cog_name_lower)
    )
    if row is None:
        row = CogState(server_id=None, cog_name=cog_name_lower, enabled=False)
        session.add(row)
    else:
        row.enabled = not row.enabled
    enabled = row.enabled
    try:
        invalidate_cog_state_cache(cog_name=cog_name)
    except Exception:  # noqa: BLE001
        pass
    return {"ok": True, "enabled": enabled}


# ---------------------------------------------------------------------------
# Per-server enable/disable (new endpoints)
# ---------------------------------------------------------------------------


@router.get("/{server_id}/enabled-cogs")
async def get_server_enabled_cogs(server_id: int, session: SessionDep) -> dict:
    """Get which cogs are enabled on a specific server."""
    from bot.database.models.server.server_cog_state import ServerCogState

    # Read from ServerCogState (what the UI uses for per-server toggles)
    sv_rows = (await session.scalars(
        select(ServerCogState).where(ServerCogState.server_id == server_id)
    )).all()
    sv_enabled = [r.cog_name for r in sv_rows if r.enabled]
    sv_disabled = [r.cog_name for r in sv_rows if not r.enabled]

    # Also check ServerConfig for backward compat
    cfg = await session.scalar(
        select(ServerConfig).where(ServerConfig.server_id == server_id)
    )
    cfg_enabled = cfg.enabled_cogs if cfg else []

    return {
        "server_id": str(server_id),
        "enabled_cogs": sv_enabled,
        "disabled_cogs": sv_disabled,
        "config_enabled_cogs": cfg_enabled,
        "available": [c["name"] for c in get_all_cog_info()],
    }


@router.put("/{server_id}/enabled-cogs/{cog_name}")
async def update_server_enabled_cog(
    server_id: int, cog_name: str, req: ServerCogEnableRequest, session: SessionDep
) -> dict:
    """Enable or disable a specific cog on a server."""
    from bot.database.models.server.server_cog_state import ServerCogState
    from datetime import UTC, datetime

    # Validate the cog exists
    valid_names = [c["name"].lower() for c in get_all_cog_info()]
    if cog_name.lower() not in valid_names:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Unknown cog '{cog_name}'. Available: {', '.join(valid_names)}",
        )

    cog_name_lower = cog_name.lower()

    # Update ServerCogState — this is what the UI reads for per-server toggle state
    sv_state = await session.scalar(
        select(ServerCogState).where(
            ServerCogState.server_id == server_id,
            ServerCogState.cog_name == cog_name_lower,
        )
    )
    if sv_state is None:
        sv_state = ServerCogState(
            server_id=server_id,
            cog_name=cog_name_lower,
            enabled=req.enabled,
            updated_at=datetime.now(tz=UTC),
        )
        session.add(sv_state)
    else:
        sv_state.enabled = req.enabled
        sv_state.updated_at = datetime.now(tz=UTC)

    # Also update ServerConfig.enabled_cogs for backward compat
    cfg = await session.scalar(
        select(ServerConfig).where(ServerConfig.server_id == server_id)
    )
    if cfg:
        enabled = list(cfg.enabled_cogs or [])
        if req.enabled:
            if cog_name_lower not in enabled:
                enabled.append(cog_name_lower)
        else:
            if cog_name_lower in enabled:
                enabled = [c for c in enabled if c != cog_name_lower]
        cfg.enabled_cogs = enabled

    try:
        invalidate_cog_state_cache(server_id=server_id, cog_name=cog_name)
    except Exception:  # noqa: BLE001
        pass
    return {"ok": True, "enabled": req.enabled}
