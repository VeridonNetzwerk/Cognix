"""Backups and server permissions routes."""

from __future__ import annotations

import uuid

from fastapi import Cookie, Form, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import desc, select

from bot.runtime import get_bot
from bot.database.models.backups.backup import Backup
from bot.database.models.auth.role_permission import RolePermission
from bot.database.models.server.server import Server
from bot.database.models.auth.web_user import WebRole
from bot.database.session import db_session
from web.deps import ACCESS_COOKIE
from bot.pages._shared import _render, _require_cog, _require_user, router


@router.get("/backups", response_class=HTMLResponse)
async def backups_view(request: Request,
                       access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE)) -> HTMLResponse:
    user = await _require_user(access_token)
    _require_cog("bot.cogs.backups.backups")
    async with db_session() as s:
        rows = (
            await s.scalars(select(Backup).order_by(desc(Backup.created_at)).limit(200))
        ).all()
        servers = (await s.scalars(select(Server).order_by(Server.name))).all()
    return _render(
        request, "backups/backups.html", user=user, backups=rows, servers=servers
    )


@router.post("/backups/create")
async def backups_create(server_id: int = Form(...),
                         name: str = Form(default=""),
                         message_limit: int = Form(default=0),
                         access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE)) -> Response:
    _require_cog("bot.cogs.backups.backups")
    me = await _require_user(access_token)
    bot = get_bot()
    if bot is None:
        raise HTTPException(503, "bot offline")
    cog = bot.get_cog("Backups")
    if cog is None:
        raise HTTPException(503, "Backups cog not loaded")
    await cog._ipc_create({  # type: ignore[attr-defined]
        "server_id": server_id,
        "name": name,
        "message_limit": message_limit,
        "created_by": 0,
        "description": f"Created by {me.username} via dashboard",
    })
    return RedirectResponse("/backups", status_code=303)


@router.post("/backups/{backup_id}/load")
async def backups_load(backup_id: str,
                       target_server_id: int = Form(...),
                       access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE)) -> Response:
    await _require_user(access_token)
    _require_cog("bot.cogs.backups.backups")
    bot = get_bot()
    if bot is None:
        raise HTTPException(503, "bot offline")
    cog = bot.get_cog("Backups")
    if cog is None:
        raise HTTPException(503, "Backups cog not loaded")
    await cog._ipc_restore({  # type: ignore[attr-defined]
        "target_server_id": target_server_id,
        "backup_id": backup_id,
    })
    return RedirectResponse("/backups", status_code=303)


@router.post("/backups/{backup_id}/delete")
async def backups_delete(backup_id: str,
                         access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE)) -> Response:
    await _require_user(access_token)
    _require_cog("bot.cogs.backups.backups")
    async with db_session() as s:
        b = await s.get(Backup, uuid.UUID(backup_id))
        if b is not None:
            await s.delete(b)
    return RedirectResponse("/backups", status_code=303)


@router.post("/servers/{server_id}/permissions")
async def server_permissions_save(server_id: int,
                                  role_id: str = Form(...),
                                  command: str = Form(...),
                                  allowed: str = Form(default=""),
                                  access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE)) -> Response:
    me = await _require_user(access_token)
    if me.role not in (WebRole.ADMIN, WebRole.MODERATOR):
        raise HTTPException(403, "forbidden")
    if not role_id.strip().isdigit() or not command.strip():
        return RedirectResponse(f"/servers/{server_id}", status_code=303)
    rid = int(role_id)
    cmd = command.strip()[:64]
    is_allowed = allowed in ("on", "true", "1", "yes")
    async with db_session() as s:
        existing = await s.scalar(
            select(RolePermission).where(
                RolePermission.server_id == server_id,
                RolePermission.discord_role_id == rid,
                RolePermission.command == cmd,
            )
        )
        if existing is None:
            s.add(RolePermission(
                server_id=server_id,
                discord_role_id=rid,
                command=cmd,
                allowed=is_allowed,
            ))
        else:
            existing.allowed = is_allowed
    return RedirectResponse(f"/servers/{server_id}", status_code=303)


@router.post("/servers/{server_id}/permissions/{perm_id}/delete")
async def server_permissions_delete(server_id: int,
                                    perm_id: int,
                                    access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE)) -> Response:
    me = await _require_user(access_token)
    if me.role not in (WebRole.ADMIN, WebRole.MODERATOR):
        raise HTTPException(403, "forbidden")
    async with db_session() as s:
        row = await s.get(RolePermission, perm_id)
        if row is not None and row.server_id == server_id:
            await s.delete(row)
    return RedirectResponse(f"/servers/{server_id}", status_code=303)
