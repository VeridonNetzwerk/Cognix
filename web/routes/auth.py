"""Auth routes: login, logout, refresh, me."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Cookie, HTTPException, Request, Response, status

from config.constants import AUDIT_LOGIN, AUDIT_LOGIN_FAILED, AUDIT_LOGOUT
from config.settings import get_settings
from database.models.audit_log import AuditLog
from web.deps import ACCESS_COOKIE, REFRESH_COOKIE, CurrentUser, SessionDep
from web.schemas.auth import LoginRequest, UserOut
from web.services.auth_service import (
    AuthError,
    authenticate,
    issue_session,
    revoke_all_sessions,
    rotate_refresh,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def _set_cookies(
    response: Response,
    access: str,
    refresh: str,
    refresh_exp: datetime,
    *,
    remember_me: bool = False,
) -> None:
    settings = get_settings()
    secure = settings.cookies_secure
    if remember_me:
        access_max_age = settings.remember_me_ttl_days * 24 * 3600
    else:
        access_max_age = settings.access_token_ttl_minutes * 60
    response.set_cookie(
        ACCESS_COOKIE,
        access,
        httponly=True,
        secure=secure,
        samesite="lax",
        max_age=access_max_age,
        path="/",
    )
    response.set_cookie(
        REFRESH_COOKIE,
        refresh,
        httponly=True,
        secure=secure,
        samesite="lax",
        max_age=int((refresh_exp - datetime.utcnow().replace(tzinfo=refresh_exp.tzinfo)).total_seconds()),
        path="/",
    )


def _clear_cookies(response: Response) -> None:
    response.delete_cookie(ACCESS_COOKIE, path="/")
    response.delete_cookie(REFRESH_COOKIE, path="/")


@router.get("/health")
async def health() -> dict:
    return {"ok": True}


@router.post("/login")
async def login(req: LoginRequest, request: Request, response: Response, session: SessionDep) -> dict:
    ip = (request.client.host if request.client else "") or ""
    ua = request.headers.get("user-agent", "")[:255]
    try:
        user = await authenticate(session, req)
    except AuthError as exc:
        session.add(
            AuditLog(action=AUDIT_LOGIN_FAILED, target=req.username, ip_address=ip, user_agent=ua)
        )
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc

    access, refresh, exp = await issue_session(session, user, user_agent=ua, ip=ip,
                                                remember_me=bool(getattr(req, "remember_me", False)))
    session.add(
        AuditLog(actor_id=user.id, action=AUDIT_LOGIN, target=user.username, ip_address=ip, user_agent=ua)
    )
    _set_cookies(response, access, refresh, exp, remember_me=bool(getattr(req, "remember_me", False)))
    return {
        "user": UserOut(
            id=str(user.id),
            username=user.username,
            email=user.email,
            role=user.role.value,
            totp_enabled=user.totp_enabled,
        ).model_dump()
    }


@router.post("/refresh")
async def refresh_endpoint(
    request: Request,
    response: Response,
    session: SessionDep,
    cognix_refresh: str | None = Cookie(default=None),
) -> dict:
    if not cognix_refresh:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "no refresh")
    ip = (request.client.host if request.client else "") or ""
    ua = request.headers.get("user-agent", "")[:255]
    try:
        access, refresh, exp, remember_me = await rotate_refresh(session, cognix_refresh, user_agent=ua, ip=ip)
    except AuthError as exc:
        _clear_cookies(response)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc
    _set_cookies(response, access, refresh, exp, remember_me=remember_me)
    return {"ok": True}


@router.post("/logout")
async def logout(response: Response, session: SessionDep, user: CurrentUser) -> dict:
    await revoke_all_sessions(session, user.id)
    session.add(AuditLog(actor_id=user.id, action=AUDIT_LOGOUT, target=user.username))
    _clear_cookies(response)
    return {"ok": True}


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser) -> UserOut:
    return UserOut(
        id=str(user.id),
        username=user.username,
        email=user.email,
        role=user.role.value,
        totp_enabled=user.totp_enabled,
    )
