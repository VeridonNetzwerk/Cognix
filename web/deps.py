"""FastAPI dependencies: DB session, current user, role guard."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated
import uuid

from fastapi import Cookie, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.web_user import WebRole, WebUser
from database.session import db_session
from web.security.tokens import TokenError, decode_token

ACCESS_COOKIE = "cognix_access"
REFRESH_COOKIE = "cognix_refresh"


async def get_db() -> AsyncIterator[AsyncSession]:
    async with db_session() as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_db)]


async def get_current_user(
    session: SessionDep,
    access_token: Annotated[str | None, Cookie(alias=ACCESS_COOKIE)] = None,
    request: Request = None,  # type: ignore[assignment]
) -> WebUser:
    token = access_token
    # Bearer fallback for API clients
    if token is None and request is not None:
        auth = request.headers.get("Authorization", "")
        if auth.lower().startswith("bearer "):
            token = auth[7:]
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "not authenticated")
    try:
        payload = decode_token(token, expected_type="access")
    except TokenError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid token") from exc
    user_id = uuid.UUID(payload["sub"])
    user = await session.get(WebUser, user_id)
    if user is None or not user.is_active or user.deleted_at is not None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "inactive user")
    return user


CurrentUser = Annotated[WebUser, Depends(get_current_user)]


def require_role(*roles: WebRole):
    """Return a dependency that checks the current user's role."""

    async def _check(user: CurrentUser) -> WebUser:
        if user.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "insufficient role")
        return user

    return _check


require_admin = require_role(WebRole.ADMIN)
require_mod = require_role(WebRole.ADMIN, WebRole.MODERATOR)
