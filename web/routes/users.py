"""Cross-server user management routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select

from database.models.moderation import ModerationAction, Warning_
from database.models.user import DiscordUser
from web.deps import SessionDep, require_mod

router = APIRouter(prefix="/users", tags=["users"], dependencies=[Depends(require_mod)])


@router.get("/")
async def list_users(session: SessionDep, q: str = "", limit: int = 50, offset: int = 0) -> dict:
    stmt = select(DiscordUser)
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(
            func.lower(DiscordUser.username).like(like)
            | func.lower(DiscordUser.global_name).like(like)
        )
    stmt = stmt.limit(limit).offset(offset).order_by(DiscordUser.username.asc())
    rows = (await session.scalars(stmt)).all()
    return {
        "items": [
            {
                "id": str(u.id),
                "username": u.username,
                "global_name": u.global_name,
                "is_bot": u.is_bot,
            }
            for u in rows
        ],
        "limit": limit,
        "offset": offset,
    }


@router.get("/{user_id}")
async def get_user(user_id: int, session: SessionDep) -> dict:
    user = await session.get(DiscordUser, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "user not found")
    warn_count = await session.scalar(
        select(func.count()).select_from(Warning_).where(Warning_.target_id == user_id)
    )
    action_count = await session.scalar(
        select(func.count())
        .select_from(ModerationAction)
        .where(ModerationAction.target_id == user_id)
    )
    return {
        "id": str(user.id),
        "username": user.username,
        "global_name": user.global_name,
        "is_bot": user.is_bot,
        "warning_count": int(warn_count or 0),
        "action_count": int(action_count or 0),
    }
