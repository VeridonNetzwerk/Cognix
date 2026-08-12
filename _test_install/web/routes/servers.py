"""Server (guild) management routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

from database.models.server import Server
from database.models.server_config import ServerConfig
from web.deps import SessionDep, require_admin, require_mod
from web.schemas.common import ServerOut

router = APIRouter(prefix="/servers", tags=["servers"], dependencies=[Depends(require_mod)])


@router.get("/", response_model=list[ServerOut])
async def list_servers(session: SessionDep) -> list[ServerOut]:
    rows = (
        await session.scalars(select(Server).where(Server.deleted_at.is_(None)))
    ).all()
    return [
        ServerOut(
            id=str(s.id),
            name=s.name,
            icon_hash=s.icon_hash,
            member_count=s.member_count,
            is_active=s.is_active,
        )
        for s in rows
    ]


@router.get("/{server_id}/config")
async def get_config(server_id: int, session: SessionDep) -> dict:
    cfg = await session.scalar(select(ServerConfig).where(ServerConfig.server_id == server_id))
    if cfg is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "server not found")
    return {
        "server_id": str(cfg.server_id),
        "prefix": cfg.prefix,
        "locale": cfg.locale,
        "mod_log_channel_id": cfg.mod_log_channel_id,
        "mute_role_id": cfg.mute_role_id,
        "welcome_channel_id": cfg.welcome_channel_id,
        "ticket_category_id": cfg.ticket_category_id,
        "ticket_support_role_ids": cfg.ticket_support_role_ids,
        "ticket_auto_close_hours": cfg.ticket_auto_close_hours,
        "music_dj_role_id": cfg.music_dj_role_id,
        "extras": cfg.extras,
    }


@router.put("/{server_id}/config", dependencies=[Depends(require_admin)])
async def update_config(server_id: int, payload: dict, session: SessionDep) -> dict:
    cfg = await session.scalar(select(ServerConfig).where(ServerConfig.server_id == server_id))
    if cfg is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "server not found")
    # Explicit allowlist — prevents setting arbitrary ORM columns via user input
    allowed: dict[str, Any] = {
        "prefix": str(payload.get("prefix", "!"))[:8],
        "locale": str(payload.get("locale", "en"))[:8],
        "mod_log_channel_id": int(payload["mod_log_channel_id"]) if payload.get("mod_log_channel_id") is not None else None,
        "mute_role_id": int(payload["mute_role_id"]) if payload.get("mute_role_id") is not None else None,
        "welcome_channel_id": int(payload["welcome_channel_id"]) if payload.get("welcome_channel_id") is not None else None,
        "ticket_category_id": int(payload["ticket_category_id"]) if payload.get("ticket_category_id") is not None else None,
        "ticket_support_role_ids": list(payload.get("ticket_support_role_ids", [])),
        "ticket_auto_close_hours": max(1, min(720, int(payload.get("ticket_auto_close_hours", 72)))) ,
        "music_dj_role_id": int(payload["music_dj_role_id"]) if payload.get("music_dj_role_id") is not None else None,
    }
    # extras field — merge carefully
    if "extras" in payload:
        extra = payload["extras"]
        if isinstance(extra, dict):
            cfg.extras.update({str(k): v for k, v in extra.items()})  # sanitize keys
    for key, value in allowed.items():
        setattr(cfg, key, value)
    return {"ok": True}
