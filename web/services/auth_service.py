"""Authentication service: login, refresh, logout."""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.web_user import RefreshToken, WebUser
from web.schemas.auth import LoginRequest
from web.security.passwords import verify_password
from web.security.tokens import (
    decode_token,
    hash_refresh_token,
    issue_access_token,
    issue_refresh_token,
)
from web.security.totp import decrypt as decrypt_totp
from web.security.totp import verify as verify_totp


class AuthError(Exception):
    """Generic auth failure (do not leak details)."""


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


async def authenticate(session: AsyncSession, req: LoginRequest) -> WebUser:
    user = await session.scalar(
        select(WebUser).where(WebUser.username == req.username, WebUser.deleted_at.is_(None))
    )
    if user is None or not user.is_active:
        raise AuthError("invalid credentials")
    if user.locked_until and user.locked_until > _now():
        raise AuthError("account locked")

    if not verify_password(req.password.get_secret_value(), user.password_hash):
        user.failed_login_count += 1
        if user.failed_login_count >= 10:
            user.locked_until = _now() + timedelta(minutes=15)
        raise AuthError("invalid credentials")

    if user.totp_enabled:
        if not req.otp:
            raise AuthError("otp required")
        secret = decrypt_totp(user.totp_secret_encrypted)
        if not verify_totp(secret, req.otp):
            user.failed_login_count += 1
            raise AuthError("invalid otp")

    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = _now()
    return user


async def issue_session(
    session: AsyncSession,
    user: WebUser,
    *,
    user_agent: str = "",
    ip: str = "",
) -> tuple[str, str, datetime]:
    """Return (access_token, refresh_token_raw, refresh_expires_at)."""
    family_id = uuid.uuid4()
    access = issue_access_token(subject=str(user.id), role=user.role.value)
    refresh, exp = issue_refresh_token(subject=str(user.id), family_id=family_id)
    session.add(
        RefreshToken(
            user_id=user.id,
            family_id=family_id,
            token_hash=hash_refresh_token(refresh),
            expires_at=exp,
            user_agent=user_agent[:255],
            ip_address=ip[:64],
        )
    )
    return access, refresh, exp


async def rotate_refresh(
    session: AsyncSession, raw_token: str, *, user_agent: str = "", ip: str = ""
) -> tuple[str, str, datetime]:
    payload = decode_token(raw_token, expected_type="refresh")
    token_hash = hash_refresh_token(raw_token)
    rt = await session.scalar(
        select(RefreshToken).where(RefreshToken.token_hash == token_hash)
    )
    if rt is None:
        # Reuse / unknown token: revoke entire family if we can identify one.
        family_hex = payload.get("fam")
        if family_hex:
            family_uuid = uuid.UUID(family_hex)
            for sibling in (
                await session.scalars(
                    select(RefreshToken).where(RefreshToken.family_id == family_uuid)
                )
            ).all():
                sibling.revoked_at = _now()
        raise AuthError("invalid refresh")

    if rt.revoked_at is not None or rt.expires_at < _now():
        # Replay attempt: revoke whole family.
        for sibling in (
            await session.scalars(
                select(RefreshToken).where(RefreshToken.family_id == rt.family_id)
            )
        ).all():
            sibling.revoked_at = _now()
        raise AuthError("refresh expired")

    rt.revoked_at = _now()
    user = await session.get(WebUser, rt.user_id)
    if user is None or not user.is_active:
        raise AuthError("user inactive")

    access = issue_access_token(subject=str(user.id), role=user.role.value)
    new_refresh, new_exp = issue_refresh_token(subject=str(user.id), family_id=rt.family_id)
    session.add(
        RefreshToken(
            user_id=user.id,
            family_id=rt.family_id,
            token_hash=hash_refresh_token(new_refresh),
            expires_at=new_exp,
            user_agent=user_agent[:255],
            ip_address=ip[:64],
        )
    )
    return access, new_refresh, new_exp


async def revoke_all_sessions(session: AsyncSession, user_id: uuid.UUID) -> None:
    rows = (
        await session.scalars(
            select(RefreshToken).where(
                RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None)
            )
        )
    ).all()
    for r in rows:
        r.revoked_at = _now()
