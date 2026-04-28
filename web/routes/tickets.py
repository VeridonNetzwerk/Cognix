"""Tickets routes (list/close from dashboard)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

from database.models.ticket import Ticket, TicketStatus
from web.deps import SessionDep, require_mod
from web.services.bot_ipc import get_ipc

router = APIRouter(prefix="/tickets", tags=["tickets"], dependencies=[Depends(require_mod)])


@router.get("/")
async def list_tickets(session: SessionDep, server_id: str | None = None) -> dict:
    stmt = select(Ticket).order_by(Ticket.created_at.desc()).limit(200)
    if server_id:
        stmt = stmt.where(Ticket.server_id == int(server_id))
    rows = (await session.scalars(stmt)).all()
    return {
        "items": [
            {
                "id": str(t.id),
                "server_id": str(t.server_id),
                "opener_id": str(t.opener_id),
                "thread_id": str(t.thread_id),
                "title": t.title,
                "category": t.category,
                "status": t.status.value,
                "created_at": t.created_at.isoformat(),
                "closed_at": t.closed_at.isoformat() if t.closed_at else None,
            }
            for t in rows
        ]
    }


@router.post("/{ticket_id}/close")
async def close_ticket(ticket_id: str, session: SessionDep) -> dict:
    ipc = get_ipc()
    res = await ipc.call("ticket.close", {"ticket_id": ticket_id}, timeout=10.0)
    if res.get("status") != "ok":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, res.get("error", "failed"))
    return {"ok": True}
