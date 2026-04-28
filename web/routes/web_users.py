"""Web user management (admin only) — Phase 10 role system.

CRUD for dashboard users: list, create, update role / active flag, delete,
reset password, force-disable 2FA.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select

from config.constants import (
    AUDIT_USER_CREATED,
    AUDIT_USER_DELETED,
    AUDIT_USER_UPDATED,
)
from database.models.audit_log import AuditLog
from database.models.web_user import WebRole, WebUser
from web.deps import SessionDep, require_admin
from web.security.passwords import hash_password

router = APIRouter(prefix="/web-users", tags=["web-users"])


class WebUserOut(BaseModel):
    id: uuid.UUID
    username: str
    email: str | None
    role: WebRole
    is_active: bool
    totp_enabled: bool

    model_config = {"from_attributes": True}


class WebUserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    email: EmailStr | None = None
    password: str = Field(min_length=8, max_length=128)
    role: WebRole = WebRole.VIEWER


class WebUserUpdate(BaseModel):
    role: WebRole | None = None
    is_active: bool | None = None
    email: EmailStr | None = None


class PasswordReset(BaseModel):
    new_password: str = Field(min_length=8, max_length=128)


def _audit(session, *, actor: WebUser, action: str, target: uuid.UUID, request: Request, **details: object) -> None:
    session.add(
        AuditLog(
            actor_id=actor.id,
            action=action,
            target=f"web_user:{target}",
            ip_address=(request.client.host if request.client else "")[:64],
            user_agent=(request.headers.get("user-agent") or "")[:255],
            details=details,
        )
    )


@router.get("", response_model=list[WebUserOut])
async def list_users(
    session: SessionDep,
    _: Annotated[WebUser, Depends(require_admin)],
) -> list[WebUser]:
    rows = (await session.scalars(select(WebUser).order_by(WebUser.username))).all()
    return list(rows)


@router.post("", response_model=WebUserOut, status_code=201)
async def create_user(
    body: WebUserCreate,
    session: SessionDep,
    request: Request,
    actor: Annotated[WebUser, Depends(require_admin)],
) -> WebUser:
    existing = await session.scalar(select(WebUser).where(WebUser.username == body.username))
    if existing:
        raise HTTPException(status.HTTP_409_CONFLICT, "username already exists")
    user = WebUser(
        username=body.username,
        email=body.email,
        password_hash=hash_password(body.password),
        role=body.role,
        is_active=True,
    )
    session.add(user)
    await session.flush()
    _audit(session, actor=actor, action=AUDIT_USER_CREATED, target=user.id,
           request=request, role=body.role.value)
    return user


@router.patch("/{user_id}", response_model=WebUserOut)
async def update_user(
    user_id: uuid.UUID,
    body: WebUserUpdate,
    session: SessionDep,
    request: Request,
    actor: Annotated[WebUser, Depends(require_admin)],
) -> WebUser:
    user = await session.get(WebUser, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not found")

    if user.id == actor.id and body.role is not None and body.role != WebRole.ADMIN:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "cannot demote yourself")
    if user.id == actor.id and body.is_active is False:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "cannot deactivate yourself")

    changes: dict[str, object] = {}
    if body.role is not None:
        changes["role"] = body.role.value
        user.role = body.role
    if body.is_active is not None:
        changes["is_active"] = body.is_active
        user.is_active = body.is_active
    if body.email is not None:
        changes["email"] = body.email
        user.email = body.email
    _audit(session, actor=actor, action=AUDIT_USER_UPDATED, target=user.id,
           request=request, **changes)
    return user


@router.post("/{user_id}/password", status_code=204)
async def reset_password(
    user_id: uuid.UUID,
    body: PasswordReset,
    session: SessionDep,
    request: Request,
    actor: Annotated[WebUser, Depends(require_admin)],
) -> None:
    user = await session.get(WebUser, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not found")
    user.password_hash = hash_password(body.new_password)
    user.failed_login_count = 0
    user.locked_until = None
    _audit(session, actor=actor, action=AUDIT_USER_UPDATED, target=user.id,
           request=request, password_reset=True)


@router.post("/{user_id}/disable-2fa", status_code=204)
async def disable_2fa(
    user_id: uuid.UUID,
    session: SessionDep,
    request: Request,
    actor: Annotated[WebUser, Depends(require_admin)],
) -> None:
    user = await session.get(WebUser, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not found")
    user.totp_enabled = False
    user.totp_secret_encrypted = ""
    _audit(session, actor=actor, action=AUDIT_USER_UPDATED, target=user.id,
           request=request, totp_disabled=True)


@router.delete("/{user_id}", status_code=204)
async def delete_user(
    user_id: uuid.UUID,
    session: SessionDep,
    request: Request,
    actor: Annotated[WebUser, Depends(require_admin)],
) -> None:
    user = await session.get(WebUser, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not found")
    if user.id == actor.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "cannot delete yourself")
    _audit(session, actor=actor, action=AUDIT_USER_DELETED, target=user.id, request=request)
    await session.delete(user)
