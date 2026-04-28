"""JWT issue/verify helpers (HS256)."""

from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt

from config.settings import get_settings

ALGO = "HS256"


class TokenError(Exception):
    """Raised when a JWT cannot be verified."""


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def issue_access_token(*, subject: str, role: str, extra: dict[str, Any] | None = None) -> str:
    settings = get_settings()
    now = _now()
    payload: dict[str, Any] = {
        "sub": subject,
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.access_token_ttl_minutes)).timestamp()),
        "jti": uuid.uuid4().hex,
        "typ": "access",
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.jwt_secret, algorithm=ALGO)


def issue_refresh_token(*, subject: str, family_id: uuid.UUID) -> tuple[str, datetime]:
    settings = get_settings()
    now = _now()
    expires = now + timedelta(days=settings.refresh_token_ttl_days)
    raw = secrets.token_urlsafe(64)
    payload = {
        "sub": subject,
        "fam": family_id.hex,
        "iat": int(now.timestamp()),
        "exp": int(expires.timestamp()),
        "typ": "refresh",
        "rnd": raw,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=ALGO), expires


def decode_token(token: str, *, expected_type: str | None = None) -> dict[str, Any]:
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[ALGO])
    except jwt.PyJWTError as exc:
        raise TokenError(str(exc)) from exc
    if expected_type and payload.get("typ") != expected_type:
        raise TokenError("unexpected token type")
    return payload


def hash_refresh_token(token: str) -> str:
    """Hash a refresh token for safe DB storage."""
    import hashlib

    return hashlib.sha256(token.encode("utf-8")).hexdigest()
