"""Backup routes."""

from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select

from config.crypto import decrypt_secret, encrypt_secret
from database.models.backup import Backup
from web.deps import CurrentUser, SessionDep, require_admin
from web.services.bot_ipc import get_ipc

router = APIRouter(prefix="/backups", tags=["backups"], dependencies=[Depends(require_admin)])


class CreateBackupRequest(BaseModel):
    server_id: str
    name: str = ""
    description: str = ""


class RestoreBackupRequest(BaseModel):
    target_server_id: str


@router.get("/")
async def list_backups(session: SessionDep, server_id: str | None = None) -> dict:
    stmt = select(Backup).order_by(Backup.created_at.desc())
    if server_id:
        stmt = stmt.where(Backup.server_id == int(server_id))
    rows = (await session.scalars(stmt)).all()
    return {
        "items": [
            {
                "id": str(b.id),
                "server_id": str(b.server_id),
                "name": b.name,
                "description": b.description,
                "summary": b.summary,
                "size_bytes": b.payload_size_bytes,
                "created_at": b.created_at.isoformat(),
            }
            for b in rows
        ]
    }


@router.post("/")
async def create_backup(req: CreateBackupRequest, session: SessionDep, user: CurrentUser) -> dict:
    ipc = get_ipc()
    res = await ipc.call(
        "backup.snapshot", {"server_id": int(req.server_id)}, timeout=20.0
    )
    payload = res.get("payload", {})
    if not payload:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "snapshot failed")
    encoded = json.dumps(payload, separators=(",", ":"))
    backup = Backup(
        server_id=int(req.server_id),
        name=req.name or f"backup-{int(__import__('time').time())}",
        description=req.description,
        created_by=0,  # web-initiated
        payload_encrypted=encrypt_secret(encoded, aad=b"backup"),
        payload_size_bytes=len(encoded),
        summary={
            "channels": len(payload.get("channels", [])),
            "roles": len(payload.get("roles", [])),
        },
    )
    session.add(backup)
    await session.flush()
    return {"id": str(backup.id)}


@router.post("/{backup_id}/restore")
async def restore_backup(
    backup_id: uuid.UUID, req: RestoreBackupRequest, session: SessionDep
) -> dict:
    backup = await session.get(Backup, backup_id)
    if backup is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "backup not found")
    payload = json.loads(decrypt_secret(backup.payload_encrypted, aad=b"backup"))
    ipc = get_ipc()
    await ipc.call(
        "backup.restore",
        {"target_server_id": int(req.target_server_id), "payload": payload},
        timeout=60.0,
    )
    return {"ok": True}


@router.get("/{backup_id}/download")
async def download_backup(backup_id: uuid.UUID, session: SessionDep) -> Response:
    """Return decrypted backup as JSON file (FEAT #4)."""
    backup = await session.get(Backup, backup_id)
    if backup is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "backup not found")
    payload = json.loads(decrypt_secret(backup.payload_encrypted, aad=b"backup"))
    body = json.dumps(
        {
            "name": backup.name,
            "description": backup.description,
            "server_id": str(backup.server_id),
            "created_at": backup.created_at.isoformat(),
            "summary": backup.summary,
            "payload": payload,
        },
        indent=2,
    ).encode("utf-8")
    safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in (backup.name or "backup"))
    date_str = backup.created_at.strftime("%Y%m%d-%H%M%S")
    filename = f"backup-{safe_name}-{date_str}.json"
    return Response(
        content=body,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
