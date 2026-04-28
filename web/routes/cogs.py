"""Cog control routes."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select

from database.models.cog_state import CogState
from web.deps import SessionDep, require_admin
from web.services.bot_ipc import get_ipc

router = APIRouter(prefix="/cogs", tags=["cogs"], dependencies=[Depends(require_admin)])


class CogActionRequest(BaseModel):
    action: Literal["load", "unload", "reload"]


@router.get("/")
async def list_cogs(session: SessionDep) -> dict:
    rows = (
        await session.scalars(select(CogState).where(CogState.server_id.is_(None)))
    ).all()
    ipc = get_ipc()
    try:
        live = await ipc.call("cog.list", {}, timeout=2.0)
        live_cogs = live.get("payload", {}).get("loaded", [])
    except Exception:  # noqa: BLE001
        live_cogs = []
    return {
        "cogs": [
            {"name": r.cog_name, "enabled": r.enabled, "loaded": r.cog_name in live_cogs}
            for r in rows
        ]
    }


@router.post("/{cog_name}")
async def cog_action(cog_name: str, req: CogActionRequest) -> dict:
    ipc = get_ipc()
    try:
        result = await ipc.call(f"cog.{req.action}", {"name": cog_name}, timeout=5.0)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "bot offline") from exc
    if result.get("status") != "ok":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, result.get("error", "failed"))
    return {"ok": True}
