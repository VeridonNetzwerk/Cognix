"""Login, logout, and setup wizard routes."""

from __future__ import annotations

from fastapi import Cookie, Form, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse

from config.constants import AUDIT_LOGOUT
from database.models.audit_log import AuditLog
from database.session import db_session
from web.deps import ACCESS_COOKIE
from web.routes.auth import _clear_cookies, _set_cookies
from web.routes.views._shared import (
    _current_user,
    _render,
    _system_configured,
    router,
)
from web.schemas.auth import LoginRequest
from web.services.auth_service import AuthError, authenticate, issue_session


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request,
                     access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE)) -> HTMLResponse:
    user = await _current_user(access_token)
    if user is not None:
        return RedirectResponse("/", status_code=303)
    if not await _system_configured():
        return RedirectResponse("/setup", status_code=303)
    return _render(request, "login.html")


@router.post("/login")
async def login_submit(request: Request,
                       username: str = Form(...),
                       password: str = Form(...),
                       totp: str | None = Form(default=None),
                       remember_me: str | None = Form(default=None)) -> Response:
    remember = bool(remember_me) and str(remember_me).lower() in ("on", "true", "1", "yes")
    ip = (request.client.host if request.client else "") or ""
    ua = request.headers.get("user-agent", "")[:255]
    try:
        async with db_session() as s:
            user = await authenticate(s, LoginRequest(username=username, password=password,
                                                     otp=totp or None, remember_me=remember))
            access, refresh, exp = await issue_session(s, user, user_agent=ua, ip=ip,
                                                       remember_me=remember)
            s.add(AuditLog(actor_id=user.id, action="auth.login", target=user.username,
                           ip_address=ip, user_agent=ua))
    except AuthError as exc:
        async with db_session() as s2:
            s2.add(AuditLog(action="auth.login_failed", target=username,
                            ip_address=ip, user_agent=ua))
        return _render(request, "login.html", error=str(exc))
    response = RedirectResponse("/", status_code=303)
    _set_cookies(response, access, refresh, exp, remember_me=remember)
    return response


@router.post("/logout")
async def logout(request: Request, response: Response,
                 access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE)) -> Response:
    user = await _current_user(access_token)
    if user is not None:
        async with db_session() as s:
            s.add(AuditLog(actor_id=user.id, action=AUDIT_LOGOUT, target=user.username))
    r = RedirectResponse("/login", status_code=303)
    _clear_cookies(r)
    return r


@router.get("/setup", response_class=HTMLResponse)
async def setup_page(request: Request) -> HTMLResponse:
    if await _system_configured():
        return RedirectResponse("/login", status_code=303)
    return _render(request, "setup.html")


@router.post("/setup")
async def setup_submit(request: Request,
                       bot_token: str = Form(...),
                       application_id: str = Form(default=""),
                       admin_username: str = Form(...),
                       admin_email: str = Form(...),
                       admin_password: str = Form(...)) -> Response:
    from web.schemas.auth import SetupRequest
    from web.services.setup_service import SetupError, perform_setup

    try:
        async with db_session() as s:
            await perform_setup(s, SetupRequest(
                bot_token=bot_token,
                bot_application_id=application_id,
                admin_username=admin_username,
                admin_email=admin_email,
                admin_password=admin_password,
            ))
    except SetupError as exc:
        return _render(request, "setup.html", error=str(exc))
    except Exception as exc:
        return _render(request, "setup.html", error=f"Setup failed: {exc}")
    return RedirectResponse("/login", status_code=303)
