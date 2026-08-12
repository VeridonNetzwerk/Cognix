"""Web user management, permissions, and settings routes."""

from __future__ import annotations

import uuid

from fastapi import Cookie, Form, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select

from config.constants import (
    AUDIT_USER_CREATED,
    AUDIT_USER_DELETED,
    AUDIT_USER_UPDATED,
)
from database.models.audit_log import AuditLog
from database.models.web_user import WebRole, WebUser
from database.models.web_user_settings import (
    MODULES,
    WebUserModulePermission,
)
from database.session import db_session
from web.deps import ACCESS_COOKIE
from web.pages._shared import _render, _require_user, router
from web.security.passwords import hash_password


@router.get("/users", response_class=HTMLResponse)
async def users_view(request: Request,
                     access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE)) -> HTMLResponse:
    user = await _require_user(access_token)
    if user.role != WebRole.ADMIN:
        return _render(request, "error.html", user=user, status=403,
                       title="Forbidden", detail="Admin only.")
    async with db_session() as s:
        rows = (await s.scalars(select(WebUser).order_by(WebUser.username))).all()
        perm_rows = (
            await s.scalars(select(WebUserModulePermission))
        ).all()
    perms_by_user: dict[str, dict[str, str]] = {}
    for p in perm_rows:
        perms_by_user.setdefault(str(p.user_id), {})[p.module] = p.level
    return _render(
        request, "users.html", user=user, users=rows,
        roles=[r.value for r in WebRole],
        modules=MODULES, perms_by_user=perms_by_user,
    )


@router.post("/users/{user_id}/permissions")
async def users_permissions_update(
    user_id: str,
    request: Request,
    access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE),
) -> Response:
    me = await _require_user(access_token)
    if me.role != WebRole.ADMIN:
        raise HTTPException(403, "admin only")
    form = await request.form()
    target_id = uuid.UUID(user_id)
    async with db_session() as s:
        target = await s.get(WebUser, target_id)
        if target is None:
            raise HTTPException(404, "user not found")
        if target.username == "admin":
            raise HTTPException(403, "admin account is locked")
        existing = {
            r.module: r
            for r in (
                await s.scalars(
                    select(WebUserModulePermission).where(
                        WebUserModulePermission.user_id == target_id
                    )
                )
            ).all()
        }
        for mod in MODULES:
            level = str(form.get(f"perm_{mod}", "read")).lower()
            if level not in ("none", "read", "write"):
                level = "read"
            row = existing.get(mod)
            if row is None:
                s.add(WebUserModulePermission(user_id=target_id, module=mod, level=level))
            else:
                row.level = level
        s.add(AuditLog(actor_id=me.id, action="user.permissions.update", target=str(target_id)))
    return RedirectResponse("/users", status_code=303)


@router.post("/users/create")
async def users_create(username: str = Form(...),
                       email: str = Form(default=""),
                       password: str = Form(...),
                       role: str = Form(default="VIEWER"),
                       access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE)) -> Response:
    me = await _require_user(access_token)
    if me.role != WebRole.ADMIN:
        raise HTTPException(403, "admin only")
    try:
        wrole = WebRole(role)
    except ValueError:
        wrole = WebRole.VIEWER
    async with db_session() as s:
        new_u = WebUser(
            username=username.strip()[:64],
            email=(email.strip() or None),
            password_hash=hash_password(password),
            role=wrole,
            is_active=True,
        )
        s.add(new_u)
        s.add(AuditLog(actor_id=me.id, action=AUDIT_USER_CREATED, target=username.strip()[:64]))
    return RedirectResponse("/users", status_code=303)


@router.post("/users/{user_id}/edit")
async def users_edit(user_id: str,
                     email: str = Form(default=""),
                     role: str = Form(default="VIEWER"),
                     password: str = Form(default=""),
                     is_active: str = Form(default=""),
                     access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE)) -> Response:
    me = await _require_user(access_token)
    if me.role != WebRole.ADMIN:
        raise HTTPException(403, "admin only")
    async with db_session() as s:
        target = await s.get(WebUser, uuid.UUID(user_id))
        if target is None:
            raise HTTPException(404, "not found")
        if target.username == "admin":
            raise HTTPException(403, "admin account is locked")
        target.email = email.strip() or None
        try:
            target.role = WebRole(role)
        except ValueError:
            pass
        target.is_active = is_active in ("on", "true", "1", "yes")
        if password.strip():
            target.password_hash = hash_password(password)
        s.add(AuditLog(actor_id=me.id, action=AUDIT_USER_UPDATED, target=target.username))
    return RedirectResponse("/users", status_code=303)


@router.post("/users/{user_id}/delete")
async def users_delete(user_id: str,
                       access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE)) -> Response:
    me = await _require_user(access_token)
    if me.role != WebRole.ADMIN:
        raise HTTPException(403, "admin only")
    async with db_session() as s:
        target = await s.get(WebUser, uuid.UUID(user_id))
        if target is None or target.id == me.id:
            return RedirectResponse("/users", status_code=303)
        if target.username == "admin":
            raise HTTPException(403, "admin account is locked")
        deleted_username = target.username
        await s.delete(target)
        s.add(AuditLog(actor_id=me.id, action=AUDIT_USER_DELETED, target=deleted_username))
    return RedirectResponse("/users", status_code=303)


@router.post("/users/{user_id}/reset-otp")
async def users_reset_otp(
    user_id: str,
    access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE),
) -> Response:
    me = await _require_user(access_token)
    if me.role != WebRole.ADMIN:
        raise HTTPException(403, "admin only")
    try:
        target_id = uuid.UUID(user_id)
    except ValueError as exc:
        raise HTTPException(400, "bad id") from exc
    async with db_session() as s:
        target = await s.get(WebUser, target_id)
        if target is None:
            raise HTTPException(404, "user not found")
        if target.username == "admin":
            raise HTTPException(403, "admin account is locked")
        target.totp_secret_encrypted = ""
        target.totp_enabled = False
        s.add(AuditLog(
            actor_id=me.id,
            action="user.otp_reset",
            target=target.username,
            details={"by": me.username},
        ))
    return RedirectResponse("/users", status_code=303)
