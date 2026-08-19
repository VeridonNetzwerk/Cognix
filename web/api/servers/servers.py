"""Server (guild) management routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

from bot.database.models.server.server import Server
from bot.database.models.server.server_config import ServerConfig
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
    # Explicit allowlist — only update fields that are present in the payload
    if "prefix" in payload:
        cfg.prefix = str(payload["prefix"])[:8]
    if "locale" in payload:
        cfg.locale = str(payload["locale"])[:8]
    if "mod_log_channel_id" in payload:
        cfg.mod_log_channel_id = int(payload["mod_log_channel_id"]) if payload["mod_log_channel_id"] is not None else None
    if "mute_role_id" in payload:
        cfg.mute_role_id = int(payload["mute_role_id"]) if payload["mute_role_id"] is not None else None
    if "welcome_channel_id" in payload:
        cfg.welcome_channel_id = int(payload["welcome_channel_id"]) if payload["welcome_channel_id"] is not None else None
    if "ticket_category_id" in payload:
        cfg.ticket_category_id = int(payload["ticket_category_id"]) if payload["ticket_category_id"] is not None else None
    if "ticket_support_role_ids" in payload:
        cfg.ticket_support_role_ids = list(payload["ticket_support_role_ids"])
    if "ticket_auto_close_hours" in payload:
        cfg.ticket_auto_close_hours = max(1, min(720, int(payload["ticket_auto_close_hours"])))
    if "music_dj_role_id" in payload:
        cfg.music_dj_role_id = int(payload["music_dj_role_id"]) if payload["music_dj_role_id"] is not None else None
    # extras field — merge carefully
    if "extras" in payload:
        extra = payload["extras"]
        if isinstance(extra, dict):
            from sqlalchemy.orm.attributes import flag_modified
            cfg.extras.update({str(k): v for k, v in extra.items()})
            flag_modified(cfg, "extras")
    return {"ok": True}
