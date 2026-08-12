"""Cross-server moderation routes (trigger via dashboard)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

from database.models.moderation import ModerationAction
from web.deps import CurrentUser, SessionDep, require_mod
from web.schemas.common import ModerationActionOut, ModerationRequest
from web.services.bot_ipc import get_ipc

router = APIRouter(
    prefix="/moderation", tags=["moderation"], dependencies=[Depends(require_mod)]
)


@router.get("/actions", response_model=list[ModerationActionOut])
async def list_actions(
    session: SessionDep, server_id: str | None = None, limit: int = 100
) -> list[ModerationActionOut]:
    stmt = select(ModerationAction).order_by(ModerationAction.created_at.desc()).limit(limit)
    if server_id:
        stmt = stmt.where(ModerationAction.server_id == int(server_id))
    rows = (await session.scalars(stmt)).all()
    return [
        ModerationActionOut(
            id=str(a.id),
            server_id=str(a.server_id),
            action_type=a.action_type.value,
            target_id=str(a.target_id) if a.target_id else None,
            moderator_id=str(a.moderator_id),
            reason=a.reason,
            created_at=a.created_at,
            expires_at=a.expires_at,
            affected_count=a.affected_count,
        )
        for a in rows
    ]


@router.post("/{action}")
async def perform(action: str, req: ModerationRequest, user: CurrentUser) -> dict:
    if action not in {"ban", "unban", "kick", "mute", "unmute", "warn", "purge"}:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "unknown action")
    if not req.server_ids:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "server_ids required")
    ipc = get_ipc()
    try:
        result = await ipc.call(
            f"moderation.{action}",
            {
                "server_ids": [int(s) for s in req.server_ids],
                "target_id": int(req.target_user_id) if req.target_user_id else None,
                "reason": req.reason,
                "duration_seconds": req.duration_seconds,
                "message_count": req.message_count,
                "web_user_id": str(user.id),
            },
            timeout=10.0,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "bot offline") from exc
    return result.get("payload", {})
