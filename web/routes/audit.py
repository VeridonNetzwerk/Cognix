"""Audit log read endpoint (admin only)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select

from database.models.audit_log import AuditLog
from database.models.web_user import WebUser
from web.deps import SessionDep, require_admin

router = APIRouter(prefix="/audit", tags=["audit"])


class AuditEntry(BaseModel):
    id: str
    actor_id: str | None
    action: str
    target: str
    ip_address: str
    details: dict
    created_at: str


@router.get("", response_model=list[AuditEntry])
async def list_audit(
    session: SessionDep,
    _: Annotated[WebUser, Depends(require_admin)],
    limit: int = Query(100, ge=1, le=500),
    action: str | None = None,
) -> list[AuditEntry]:
    stmt = select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    rows = (await session.scalars(stmt)).all()
    return [
        AuditEntry(
            id=str(r.id),
            actor_id=str(r.actor_id) if r.actor_id else None,
            action=r.action,
            target=r.target,
            ip_address=r.ip_address,
            details=r.details,
            created_at=r.created_at.isoformat(),
        )
        for r in rows
    ]
