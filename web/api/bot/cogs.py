"""Cog control routes — enhanced with global load state and per-server enable/disable."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select

from bot.cogs.registry import get_all_cog_info, get_loaded_cogs
from bot.database.models.server.server_config import ServerConfig
from web.deps import SessionDep, require_admin
from web.services.bot_ipc import get_ipc

router = APIRouter(prefix="/cogs", tags=["cogs"], dependencies=[Depends(require_admin)])


class CogActionRequest(BaseModel):
    action: Literal["load", "unload", "reload"]


class ServerCogEnableRequest(BaseModel):
    cog_name: str
    enabled: bool


# ---------------------------------------------------------------------------
# Global load state (what cogs are currently loaded on the bot)
# ---------------------------------------------------------------------------


@router.get("/")
async def list_cogs(session: SessionDep) -> dict:
    """Return all loaded cogs with their global load status and per-server enable status."""
    # Get global load state from runtime
    ipc = get_ipc()
    try:
        live = await ipc.call("cog.list", {}, timeout=2.0)
        live_cogs = set(live.get("payload", {}).get("loaded", []))
    except Exception:  # noqa: BLE001
        live_cogs = set()

    # Also check loaded cogs from registry
    live_cogs |= set(get_loaded_cogs())

    # Get available cogs from registry (only those actually loaded)
    all_cogs = get_all_cog_info()
    loaded_cogs = [info for info in all_cogs if info["module"] in live_cogs]

    # Also include loaded extensions not in registry (e.g. externally installed)
    registry_modules = {info["module"] for info in all_cogs}
    for ext in live_cogs:
        if ext not in registry_modules:
            short = ext.rsplit(".", 1)[-1]
            loaded_cogs.append({
                "module": ext,
                "name": short.replace("_", " ").title(),
                "description": "",
                "category": "",
                "requires_admin": False,
            })

    return {
        "cogs": [
            {
                "name": info["name"],
                "module": info["module"],
                "description": info.get("description", ""),
                "category": info.get("category", ""),
                "loaded": True,
                "requires_admin": info.get("requires_admin", False),
            }
            for info in loaded_cogs
        ],
        "loaded_count": len(loaded_cogs),
    }


# ---------------------------------------------------------------------------
# Standard cog actions (load/unload/reload via IPC)
# ---------------------------------------------------------------------------


@router.post("/{cog_name}")
async def cog_action(cog_name: str, req: CogActionRequest) -> dict:
    """Load/unload/reload a cog globally (affects all servers)."""
    ipc = get_ipc()
    try:
        result = await ipc.call(f"cog.{req.action}", {"name": cog_name}, timeout=5.0)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "bot offline") from exc
    if result.get("status") != "ok":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, result.get("error", "failed"))
    return {"ok": True}


# ---------------------------------------------------------------------------
# Per-server enable/disable (new endpoints)
# ---------------------------------------------------------------------------


@router.get("/{server_id}/enabled-cogs")
async def get_server_enabled_cogs(server_id: int, session: SessionDep) -> dict:
    """Get which cogs are enabled on a specific server."""
    cfg = await session.scalar(
        select(ServerConfig).where(ServerConfig.server_id == server_id)
    )
    if not cfg:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "server not found")

    enabled = cfg.enabled_cogs or []
    return {
        "server_id": str(server_id),
        "enabled_cogs": enabled,
        "available": [c["name"] for c in get_all_cog_info()],
    }


@router.put("/{server_id}/enabled-cogs/{cog_name}")
async def update_server_enabled_cog(
    server_id: int, cog_name: str, req: ServerCogEnableRequest, session: SessionDep
) -> dict:
    """Enable or disable a specific cog on a server."""
    cfg = await session.scalar(
        select(ServerConfig).where(ServerConfig.server_id == server_id)
    )
    if not cfg:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "server not found")

    # Validate the cog exists
    valid_names = [c["name"].lower() for c in get_all_cog_info()]
    if cog_name.lower() not in valid_names:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Unknown cog '{cog_name}'. Available: {', '.join(valid_names)}",
        )

    enabled = cfg.enabled_cogs or []
    if req.enabled:
        if cog_name.lower() not in enabled:
            enabled.append(cog_name.lower())
    else:
        if cog_name.lower() in enabled:
            enabled.remove(cog_name.lower())

    cfg.enabled_cogs = enabled
    return {"ok": True, "enabled_cogs": enabled}
