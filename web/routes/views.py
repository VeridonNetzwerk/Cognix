"""Server-rendered HTML views (Jinja2 dashboard).

This is the primary user-facing surface. It uses the same DB models as the
JSON API and reuses ``auth_service`` for login. Authentication is via the
``cognix_access`` HttpOnly cookie set by the JSON ``/api/v1/auth/login``
endpoint, but we also accept HTML form posts here for ergonomics.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Cookie, Form, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import desc, func, select

from bot.runtime import get_bot, get_bot_info
from database.models.audit_log import AuditLog
from database.models.backup import Backup
from database.models.cog_state import CogState
from database.models.discord_event import DiscordEvent, DiscordEventType
from database.models.role_permission import RolePermission
from database.models.server import Server
from database.models.server_cog_state import ServerCogState
from database.models.server_config import ServerConfig
from database.models.system_config import SystemConfig
from database.models.ticket import Ticket, TicketStatus
from database.models.web_user import WebRole, WebUser
from database.session import db_session
from web.deps import ACCESS_COOKIE, REFRESH_COOKIE
from web.routes.auth import _clear_cookies, _set_cookies
from web.schemas.auth import LoginRequest
from web.security.passwords import hash_password
from web.security.tokens import TokenError, decode_token
from web.services.auth_service import AuthError, authenticate, issue_session

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

router = APIRouter(include_in_schema=False)


# ------------------------------------------------------------- helpers

async def _current_user(access_token: str | None) -> WebUser | None:
    if not access_token:
        return None
    try:
        payload = decode_token(access_token, expected_type="access")
    except TokenError:
        return None
    try:
        user_id = uuid.UUID(payload["sub"])
    except (KeyError, ValueError):
        return None
    async with db_session() as s:
        user = await s.get(WebUser, user_id)
        if user is None or not user.is_active or user.deleted_at is not None:
            return None
        return user


async def _system_configured() -> bool:
    async with db_session() as s:
        row = await s.scalar(select(SystemConfig).where(SystemConfig.id == 1))
        return bool(row and row.configured)


def _render(request: Request, template: str, **ctx: Any) -> HTMLResponse:
    ctx.setdefault("user", None)
    ctx.setdefault("bot_info", get_bot_info())
    ctx.setdefault("user_settings", None)
    return templates.TemplateResponse(request, template, ctx)



# ------------------------------------------------------------- login / setup

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
                       totp: str | None = Form(default=None)) -> Response:
    try:
        async with db_session() as s:
            user = await authenticate(s, LoginRequest(username=username, password=password,
                                                     otp=totp or None))
            ip = (request.client.host if request.client else "") or ""
            ua = request.headers.get("user-agent", "")[:255]
            access, refresh, exp = await issue_session(s, user, user_agent=ua, ip=ip)
    except AuthError as exc:
        return _render(request, "login.html", error=str(exc))
    response = RedirectResponse("/", status_code=303)
    _set_cookies(response, access, refresh, exp)
    return response


@router.post("/logout")
async def logout(response: Response) -> Response:
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
    return RedirectResponse("/login", status_code=303)


# ------------------------------------------------------------- guard

async def _require_user(access_token: str | None) -> WebUser:
    user = await _current_user(access_token)
    if user is None:
        raise HTTPException(status.HTTP_307_TEMPORARY_REDIRECT,
                            headers={"Location": "/login"})
    return user


# ------------------------------------------------------------- dashboard

@router.get("/", response_class=HTMLResponse)
async def index(request: Request,
                access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE)) -> HTMLResponse:
    if not await _system_configured():
        return RedirectResponse("/setup", status_code=303)
    user = await _current_user(access_token)
    if user is None:
        return RedirectResponse("/login", status_code=303)

    async with db_session() as s:
        servers_count = (await s.scalar(select(func.count(Server.id)))) or 0
        users_count = (await s.scalar(
            select(func.coalesce(func.sum(Server.member_count), 0))
        )) or 0
        cogs_count = (await s.scalar(
            select(func.count(CogState.id)).where(CogState.enabled.is_(True))
        )) or 0
        open_tickets = (await s.scalar(
            select(func.count(Ticket.id)).where(Ticket.status == TicketStatus.OPEN)
        )) or 0
        recent = (await s.scalars(
            select(AuditLog).order_by(desc(AuditLog.created_at)).limit(8)
        )).all()

    info = get_bot_info()
    metrics = {
        "servers": servers_count,
        "users": users_count,
        "cogs_loaded": cogs_count,
        "open_tickets": open_tickets,
        "bot_online": info["online"],
        "uptime": info["uptime"],
        "latency_ms": info["latency_ms"],
        "guild_count": info["guild_count"],
        "user_count": info["user_count"],
        "version": info["version"],
    }
    return _render(request, "dashboard.html", user=user, metrics=metrics, recent_audit=recent)


# ------------------------------------------------------------- servers

@router.get("/servers", response_class=HTMLResponse)
async def servers_view(request: Request,
                       access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE)) -> HTMLResponse:
    user = await _require_user(access_token)
    async with db_session() as s:
        rows = (await s.scalars(select(Server).order_by(Server.name))).all()
    return _render(request, "servers.html", user=user, servers=rows)


@router.get("/servers/{server_id}", response_class=HTMLResponse)
async def server_detail(request: Request, server_id: int,
                        access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE)) -> HTMLResponse:
    user = await _require_user(access_token)
    async with db_session() as s:
        srv = await s.get(Server, server_id)
        cfg = await s.get(ServerConfig, server_id)
        perms = (
            await s.scalars(
                select(RolePermission).where(RolePermission.server_id == server_id)
            )
        ).all()
    if srv is None:
        return _render(request, "error.html", user=user, status=404,
                       title="Server not found", detail="No such server.")
    return _render(
        request,
        "server_detail.html",
        user=user,
        server=srv,
        config=cfg or {},
        permissions=perms,
    )


# ------------------------------------------------------------- cogs

@router.get("/cogs", response_class=HTMLResponse)
async def cogs_view(request: Request,
                    access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE)) -> HTMLResponse:
    user = await _require_user(access_token)
    async with db_session() as s:
        rows = (await s.scalars(
            select(CogState).where(CogState.server_id.is_(None)).order_by(CogState.cog_name)
        )).all()
    state_by_name = {r.cog_name: r.enabled for r in rows}

    # Merge with the bot's actually-loaded extensions so the page is never blank.
    bot = get_bot()
    loaded: list[str] = []
    if bot is not None:
        for ext in bot.extensions.keys():
            short = ext.rsplit(".", 1)[-1]
            loaded.append(short)
    for name in loaded:
        state_by_name.setdefault(name, True)

    descriptions = {
        "moderation": "Bans, kicks, timeouts, warnings, automod logging.",
        "tickets": "Private support threads with claim / transcript / close.",
        "music": "Wavelink-based music player with /music-panel.",
        "embeds": "Embed designer + broadcasting via /embed.",
        "stats": "Member, message and voice stat collection.",
        "utility": "/userinfo, /serverinfo, /ping, /help.",
        "backups": "/backup create|list|load|delete with encrypted DB storage.",
        "auto_punish": "Severity-based escalation rules.",
        "scheduler": "Recurring jobs and reminders.",
        "voice_features": "Auto voice channels and voice rewards.",
        "logging_audit": "Mirror of audit-log changes into Discord.",
    }
    cogs = sorted(
        (
            {
                "name": name,
                "enabled": state_by_name[name],
                "loaded": name in loaded,
                "description": descriptions.get(name, ""),
            }
            for name in state_by_name
        ),
        key=lambda c: c["name"],
    )

    # Per-server matrix: rows = servers, cols = cog names.
    async with db_session() as s:
        servers = (await s.scalars(select(Server).order_by(Server.name))).all()
        per_server_rows = (await s.scalars(select(ServerCogState))).all()
    per_server: dict[int, dict[str, bool]] = {}
    for r in per_server_rows:
        per_server.setdefault(r.server_id, {})[r.cog_name] = r.enabled
    cog_names = [c["name"] for c in cogs]
    return _render(
        request,
        "cogs.html",
        user=user,
        cogs=cogs,
        servers=servers,
        per_server=per_server,
        cog_names=cog_names,
    )


@router.post("/cogs/server/{server_id}/{cog_name}/toggle")
async def cogs_server_toggle(
    server_id: int,
    cog_name: str,
    access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE),
) -> Response:
    from datetime import datetime as _dt
    from datetime import timezone as _tz

    await _require_user(access_token)
    async with db_session() as s:
        row = await s.scalar(
            select(ServerCogState).where(
                ServerCogState.server_id == server_id,
                ServerCogState.cog_name == cog_name,
            )
        )
        if row is None:
            row = ServerCogState(
                server_id=server_id,
                cog_name=cog_name,
                enabled=False,
                updated_at=_dt.now(tz=_tz.utc),
            )
            s.add(row)
        else:
            row.enabled = not row.enabled
            row.updated_at = _dt.now(tz=_tz.utc)
    # Bust cache
    try:
        from bot.runtime import invalidate_cog_state_cache

        invalidate_cog_state_cache(server_id=server_id, cog_name=cog_name)
    except Exception:  # noqa: BLE001
        pass
    return RedirectResponse("/cogs", status_code=303)


@router.post("/cogs/{cog_name}/toggle")
async def cogs_toggle(cog_name: str,
                      access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE)) -> Response:
    await _require_user(access_token)
    async with db_session() as s:
        row = await s.scalar(
            select(CogState).where(CogState.server_id.is_(None), CogState.cog_name == cog_name)
        )
        if row is None:
            row = CogState(server_id=None, cog_name=cog_name, enabled=False)
            s.add(row)
        row.enabled = not row.enabled
    return RedirectResponse("/cogs", status_code=303)


@router.post("/cogs/{cog_name}/reload")
async def cogs_reload(cog_name: str,
                      access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE)) -> Response:
    await _require_user(access_token)
    from web.services.bot_ipc import get_ipc
    try:
        await get_ipc().call("cog.reload", {"name": cog_name}, timeout=5.0)
    except Exception:  # noqa: BLE001
        pass  # silent — surface via bot logs
    return RedirectResponse("/cogs", status_code=303)


# ------------------------------------------------------------- tickets, audit, users, embeds, music

@router.get("/embeds", response_class=HTMLResponse)
async def embeds_view(request: Request,
                      access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE)) -> HTMLResponse:
    user = await _require_user(access_token)
    return _render(request, "embeds.html", user=user)


@router.get("/music", response_class=HTMLResponse)
async def music_view(request: Request,
                     access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE)) -> HTMLResponse:
    user = await _require_user(access_token)
    return _render(request, "music.html", user=user)


@router.get("/tickets", response_class=HTMLResponse)
async def tickets_view(request: Request,
                       status_filter: str | None = None,
                       access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE)) -> HTMLResponse:
    user = await _require_user(access_token)
    async with db_session() as s:
        q = select(Ticket).order_by(desc(Ticket.created_at)).limit(200)
        if status_filter in ("open", "closed", "archived"):
            q = q.where(Ticket.status == TicketStatus(status_filter))
        tickets = (await s.scalars(q)).all()
        servers = (await s.scalars(select(Server).order_by(Server.name))).all()
    return _render(
        request,
        "tickets.html",
        user=user,
        tickets=tickets,
        servers=servers,
        status_filter=status_filter or "",
    )


@router.post("/tickets/{ticket_id}/close")
async def tickets_close(ticket_id: str,
                        access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE)) -> Response:
    await _require_user(access_token)
    from web.services.bot_ipc import get_ipc
    try:
        await get_ipc().call("ticket.close", {"ticket_id": ticket_id}, timeout=5.0)
    except Exception:  # noqa: BLE001
        # Fall back to in-process bot when Redis IPC is disabled.
        bot = get_bot()
        if bot is not None:
            cog = bot.get_cog("Tickets")
            if cog is not None:
                await cog._ipc_close({"ticket_id": ticket_id})  # type: ignore[attr-defined]
    return RedirectResponse("/tickets", status_code=303)


@router.post("/tickets/save")
async def tickets_save(server_id: int = Form(...),
                       ticket_category_id: str = Form(default=""),
                       ticket_support_role_ids: str = Form(default=""),
                       access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE)) -> Response:
    await _require_user(access_token)
    role_ids = [int(x.strip()) for x in ticket_support_role_ids.split(",") if x.strip().isdigit()]
    async with db_session() as s:
        cfg = await s.get(ServerConfig, server_id)
        if cfg is None:
            cfg = ServerConfig(server_id=server_id)
            s.add(cfg)
        cfg.ticket_category_id = int(ticket_category_id) if ticket_category_id.strip().isdigit() else None
        cfg.ticket_support_role_ids = role_ids
        # ticket_auto_close_hours retained in DB but not exposed; auto-close removed.
    return RedirectResponse("/tickets", status_code=303)


@router.get("/audit", response_class=HTMLResponse)
async def audit_view(request: Request,
                     action: str | None = None,
                     actor_id: str | None = None,
                     date_from: str | None = None,
                     date_to: str | None = None,
                     access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE)) -> HTMLResponse:
    user = await _require_user(access_token)
    if user.role != WebRole.ADMIN:
        return _render(request, "error.html", user=user, status=403,
                       title="Forbidden", detail="Admin only.")
    from datetime import datetime as _dt
    async with db_session() as s:
        q = select(AuditLog).order_by(desc(AuditLog.created_at)).limit(500)
        if action:
            q = q.where(AuditLog.action.ilike(f"%{action}%"))
        if actor_id:
            try:
                q = q.where(AuditLog.actor_id == uuid.UUID(actor_id))
            except ValueError:
                pass
        if date_from:
            try:
                q = q.where(AuditLog.created_at >= _dt.fromisoformat(date_from))
            except ValueError:
                pass
        if date_to:
            try:
                q = q.where(AuditLog.created_at <= _dt.fromisoformat(date_to))
            except ValueError:
                pass
        rows = (await s.scalars(q)).all()
    return _render(
        request,
        "audit.html",
        user=user,
        events=rows,
        filters={
            "action": action or "",
            "actor_id": actor_id or "",
            "date_from": date_from or "",
            "date_to": date_to or "",
        },
    )


@router.get("/discord-log", response_class=HTMLResponse)
async def discord_log_view(request: Request,
                           server_id: str | None = None,
                           event_type: str | None = None,
                           user_id: str | None = None,
                           date_from: str | None = None,
                           date_to: str | None = None,
                           access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE)) -> HTMLResponse:
    me = await _require_user(access_token)
    if me.role == WebRole.VIEWER:
        return _render(request, "error.html", user=me, status=403,
                       title="Forbidden", detail="Moderator+ only.")
    from datetime import datetime as _dt
    async with db_session() as s:
        q = select(DiscordEvent).order_by(desc(DiscordEvent.created_at)).limit(500)
        if server_id and server_id.isdigit():
            q = q.where(DiscordEvent.server_id == int(server_id))
        if event_type:
            try:
                q = q.where(DiscordEvent.event_type == DiscordEventType(event_type))
            except ValueError:
                pass
        if user_id and user_id.isdigit():
            q = q.where(DiscordEvent.user_id == int(user_id))
        if date_from:
            try:
                q = q.where(DiscordEvent.created_at >= _dt.fromisoformat(date_from))
            except ValueError:
                pass
        if date_to:
            try:
                q = q.where(DiscordEvent.created_at <= _dt.fromisoformat(date_to))
            except ValueError:
                pass
        rows = (await s.scalars(q)).all()
        servers = (await s.scalars(select(Server).order_by(Server.name))).all()
    return _render(
        request,
        "discord_log.html",
        user=me,
        events=rows,
        servers=servers,
        event_types=[t.value for t in DiscordEventType],
        filters={
            "server_id": server_id or "",
            "event_type": event_type or "",
            "user_id": user_id or "",
            "date_from": date_from or "",
            "date_to": date_to or "",
        },
    )


@router.get("/users", response_class=HTMLResponse)
async def users_view(request: Request,
                     access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE)) -> HTMLResponse:
    user = await _require_user(access_token)
    if user.role != WebRole.ADMIN:
        return _render(request, "error.html", user=user, status=403,
                       title="Forbidden", detail="Admin only.")
    async with db_session() as s:
        rows = (await s.scalars(select(WebUser).order_by(WebUser.username))).all()
    return _render(request, "users.html", user=user, users=rows, roles=[r.value for r in WebRole])


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
        s.add(WebUser(
            username=username.strip()[:64],
            email=(email.strip() or None),
            password_hash=hash_password(password),
            role=wrole,
            is_active=True,
        ))
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
        await s.delete(target)
    return RedirectResponse("/users", status_code=303)


# ------------------------------------------------------------- backups

@router.get("/backups", response_class=HTMLResponse)
async def backups_view(request: Request,
                       access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE)) -> HTMLResponse:
    user = await _require_user(access_token)
    async with db_session() as s:
        rows = (
            await s.scalars(select(Backup).order_by(desc(Backup.created_at)).limit(200))
        ).all()
        servers = (await s.scalars(select(Server).order_by(Server.name))).all()
    return _render(
        request, "backups.html", user=user, backups=rows, servers=servers
    )


@router.post("/backups/create")
async def backups_create(server_id: int = Form(...),
                         name: str = Form(default=""),
                         message_limit: int = Form(default=0),
                         access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE)) -> Response:
    me = await _require_user(access_token)
    bot = get_bot()
    if bot is None:
        raise HTTPException(503, "bot offline")
    cog = bot.get_cog("Backups")
    if cog is None:
        raise HTTPException(503, "Backups cog not loaded")
    await cog._ipc_create({  # type: ignore[attr-defined]
        "server_id": server_id,
        "name": name,
        "message_limit": message_limit,
        "created_by": 0,
        "description": f"Created by {me.username} via dashboard",
    })
    return RedirectResponse("/backups", status_code=303)


@router.post("/backups/{backup_id}/load")
async def backups_load(backup_id: str,
                       target_server_id: int = Form(...),
                       access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE)) -> Response:
    await _require_user(access_token)
    bot = get_bot()
    if bot is None:
        raise HTTPException(503, "bot offline")
    cog = bot.get_cog("Backups")
    if cog is None:
        raise HTTPException(503, "Backups cog not loaded")
    await cog._ipc_restore({  # type: ignore[attr-defined]
        "target_server_id": target_server_id,
        "backup_id": backup_id,
    })
    return RedirectResponse("/backups", status_code=303)


@router.post("/backups/{backup_id}/delete")
async def backups_delete(backup_id: str,
                         access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE)) -> Response:
    await _require_user(access_token)
    async with db_session() as s:
        b = await s.get(Backup, uuid.UUID(backup_id))
        if b is not None:
            await s.delete(b)
    return RedirectResponse("/backups", status_code=303)


# ------------------------------------------------------------- server permissions

@router.post("/servers/{server_id}/permissions")
async def server_permissions_save(server_id: int,
                                  role_id: str = Form(...),
                                  command: str = Form(...),
                                  allowed: str = Form(default=""),
                                  access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE)) -> Response:
    me = await _require_user(access_token)
    if me.role not in (WebRole.ADMIN, WebRole.MODERATOR):
        raise HTTPException(403, "forbidden")
    if not role_id.strip().isdigit() or not command.strip():
        return RedirectResponse(f"/servers/{server_id}", status_code=303)
    rid = int(role_id)
    cmd = command.strip()[:64]
    is_allowed = allowed in ("on", "true", "1", "yes")
    async with db_session() as s:
        existing = await s.scalar(
            select(RolePermission).where(
                RolePermission.server_id == server_id,
                RolePermission.discord_role_id == rid,
                RolePermission.command == cmd,
            )
        )
        if existing is None:
            s.add(RolePermission(
                server_id=server_id,
                discord_role_id=rid,
                command=cmd,
                allowed=is_allowed,
            ))
        else:
            existing.allowed = is_allowed
    return RedirectResponse(f"/servers/{server_id}", status_code=303)


@router.post("/servers/{server_id}/permissions/{perm_id}/delete")
async def server_permissions_delete(server_id: int,
                                    perm_id: int,
                                    access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE)) -> Response:
    me = await _require_user(access_token)
    if me.role not in (WebRole.ADMIN, WebRole.MODERATOR):
        raise HTTPException(403, "forbidden")
    async with db_session() as s:
        row = await s.get(RolePermission, perm_id)
        if row is not None and row.server_id == server_id:
            await s.delete(row)
    return RedirectResponse(f"/servers/{server_id}", status_code=303)

# ===== Phase 2: settings, 2FA, permissions, bot profile, archive, music ====

# ===== Phase 2 routes appended below =====

from datetime import datetime as _dt2
from datetime import timezone as _tz2
from base64 import b64decode as _b64decode

from database.models.bot_profile import BotProfile
from database.models.discord_message_cache import DiscordMessageCache
from database.models.music_playlist import MusicPlaylist
from database.models.web_user import BackupCode
from database.models.web_user_settings import (
    MODULES,
    WebUserModulePermission,
    WebUserSettings,
)
from web.security import totp as _totp
from web.security.permissions import get_permission_map, has_permission


async def _get_or_create_settings(session, user) -> WebUserSettings:
    row = await session.get(WebUserSettings, user.id)
    if row is None:
        row = WebUserSettings(user_id=user.id, updated_at=_dt2.now(tz=_tz2.utc))
        session.add(row)
    return row


# -------------------- /settings (theme + font + 2FA + permissions) -------

@router.get("/settings", response_class=HTMLResponse)
async def settings_view(
    request: Request,
    access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE),
) -> HTMLResponse:
    user = await _require_user(access_token)
    async with db_session() as s:
        settings = await _get_or_create_settings(s, user)
        all_users = []
        if user.role == WebRole.ADMIN:
            all_users = (await s.scalars(select(WebUser).order_by(WebUser.username))).all()
            user_perms = {}
            for u in all_users:
                user_perms[str(u.id)] = await get_permission_map(s, u)
        else:
            user_perms = {str(user.id): await get_permission_map(s, user)}
    return _render(
        request,
        "settings.html",
        user=user,
        settings=settings,
        modules=MODULES,
        levels=["none", "read", "write"],
        all_users=all_users,
        user_perms=user_perms,
    )


@router.post("/settings/appearance")
async def settings_appearance(
    theme: str = Form("dark"),
    accent_color: str = Form("#60A5FA"),
    font_size: str = Form("medium"),
    access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE),
) -> Response:
    user = await _require_user(access_token)
    if theme not in ("dark", "light", "custom"):
        theme = "dark"
    if font_size not in ("small", "medium", "large"):
        font_size = "medium"
    async with db_session() as s:
        row = await _get_or_create_settings(s, user)
        row.theme = theme
        row.accent_color = accent_color[:16]
        row.font_size = font_size
        row.updated_at = _dt2.now(tz=_tz2.utc)
    return RedirectResponse("/settings", status_code=303)


@router.post("/settings/2fa/enable")
async def settings_2fa_enable(
    request: Request,
    access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE),
) -> HTMLResponse:
    user = await _require_user(access_token)
    if user.totp_enabled:
        return RedirectResponse("/settings", status_code=303)
    secret = _totp.generate_secret()
    uri = _totp.provisioning_uri(secret, account=user.email or user.username)
    qr_url = _totp.qr_data_url(uri)
    async with db_session() as s:
        target = await s.get(WebUser, user.id)
        target.totp_secret_encrypted = _totp.encrypted_secret(secret)
    return _render(
        request,
        "settings_2fa_setup.html",
        user=user,
        secret=secret,
        qr_url=qr_url,
    )


@router.post("/settings/2fa/verify")
async def settings_2fa_verify(
    request: Request,
    code: str = Form(...),
    access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE),
) -> Response:
    user = await _require_user(access_token)
    import hashlib as _h
    async with db_session() as s:
        target = await s.get(WebUser, user.id)
        if not target.totp_secret_encrypted:
            raise HTTPException(400, "no pending TOTP setup")
        secret = _totp.decrypt(target.totp_secret_encrypted)
        if not _totp.verify(secret, code):
            raise HTTPException(400, "invalid code")
        target.totp_enabled = True
        existing = (
            await s.scalars(select(BackupCode).where(BackupCode.user_id == user.id))
        ).all()
        for old in existing:
            await s.delete(old)
        codes = _totp.generate_backup_codes(8)
        for raw in codes:
            s.add(BackupCode(user_id=user.id, code_hash=_h.sha256(raw.encode()).hexdigest()))
    return _render(request, "settings_2fa_codes.html", user=user, codes=codes)


@router.post("/settings/2fa/disable")
async def settings_2fa_disable(
    password: str = Form(...),
    code: str = Form(...),
    access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE),
) -> Response:
    user = await _require_user(access_token)
    from web.security.passwords import verify_password
    if not verify_password(password, user.password_hash):
        raise HTTPException(400, "invalid password")
    if not user.totp_enabled or not _totp.verify(_totp.decrypt(user.totp_secret_encrypted), code):
        raise HTTPException(400, "invalid code")
    async with db_session() as s:
        target = await s.get(WebUser, user.id)
        target.totp_enabled = False
        target.totp_secret_encrypted = ""
        existing = (
            await s.scalars(select(BackupCode).where(BackupCode.user_id == user.id))
        ).all()
        for old in existing:
            await s.delete(old)
    return RedirectResponse("/settings", status_code=303)


@router.post("/settings/permissions/{user_id}")
async def settings_permissions_update(
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
    return RedirectResponse("/settings", status_code=303)


# -------------------- /bot-profile --------------------------------------

@router.get("/bot-profile", response_class=HTMLResponse)
async def bot_profile_view(
    request: Request,
    access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE),
) -> HTMLResponse:
    user = await _require_user(access_token)
    async with db_session() as s:
        if not await has_permission(s, user, "bot_profile", level="read"):
            raise HTTPException(403, "forbidden")
        prof = await s.get(BotProfile, 1)
        if prof is None:
            prof = BotProfile(id=1, updated_at=_dt2.now(tz=_tz2.utc))
            s.add(prof)
            await s.flush()
    return _render(request, "bot_profile.html", user=user, profile=prof)


@router.post("/bot-profile")
async def bot_profile_save(
    request: Request,
    display_name: str = Form(""),
    about_me: str = Form(""),
    avatar_data: str = Form(""),
    banner_data: str = Form(""),
    activity_type: str = Form("playing"),
    activity_text: str = Form(""),
    status: str = Form("online"),
    access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE),
) -> Response:
    user = await _require_user(access_token)
    async with db_session() as s:
        if not await has_permission(s, user, "bot_profile", level="write"):
            raise HTTPException(403, "forbidden")
        prof = await s.get(BotProfile, 1)
        if prof is None:
            prof = BotProfile(id=1, updated_at=_dt2.now(tz=_tz2.utc))
            s.add(prof)
        prof.display_name = display_name[:64]
        prof.about_me = about_me[:512]
        if avatar_data.startswith("data:"):
            prof.avatar_data = avatar_data[:1_000_000]
        if banner_data.startswith("data:"):
            prof.banner_data = banner_data[:2_000_000]
        prof.activity_type = activity_type if activity_type in ("playing","listening","watching","competing","streaming") else "playing"
        prof.activity_text = activity_text[:128]
        prof.status = status if status in ("online","idle","dnd","invisible") else "online"
        prof.updated_at = _dt2.now(tz=_tz2.utc)

    # Apply to live bot
    bot = get_bot()
    if bot is not None and bot.user is not None:
        try:
            import discord as _d
            kwargs: dict = {}
            if display_name and display_name != bot.user.name:
                kwargs["username"] = display_name
            if avatar_data.startswith("data:image"):
                try:
                    raw = _b64decode(avatar_data.split(",", 1)[1])
                    kwargs["avatar"] = raw
                except Exception:
                    pass
            if banner_data.startswith("data:image"):
                try:
                    raw = _b64decode(banner_data.split(",", 1)[1])
                    kwargs["banner"] = raw
                except Exception:
                    pass
            if kwargs:
                try:
                    await bot.user.edit(**kwargs)
                except Exception:
                    pass
            atype_map = {
                "playing": _d.ActivityType.playing,
                "listening": _d.ActivityType.listening,
                "watching": _d.ActivityType.watching,
                "competing": _d.ActivityType.competing,
                "streaming": _d.ActivityType.streaming,
            }
            status_map = {
                "online": _d.Status.online,
                "idle": _d.Status.idle,
                "dnd": _d.Status.dnd,
                "invisible": _d.Status.invisible,
            }
            activity = _d.Activity(type=atype_map.get(activity_type, _d.ActivityType.playing), name=activity_text or "Cognix")
            await bot.change_presence(activity=activity, status=status_map.get(status, _d.Status.online))
        except Exception:
            pass
    return RedirectResponse("/bot-profile", status_code=303)


# -------------------- archived ticket viewer ----------------------------

@router.get("/tickets/{ticket_id}", response_class=HTMLResponse)
async def ticket_view(
    ticket_id: str,
    request: Request,
    access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE),
) -> HTMLResponse:
    user = await _require_user(access_token)
    try:
        tid = uuid.UUID(ticket_id)
    except ValueError:
        raise HTTPException(404, "not found")
    async with db_session() as s:
        if not await has_permission(s, user, "tickets", level="read"):
            raise HTTPException(403, "forbidden")
        ticket = await s.get(Ticket, tid)
        if ticket is None:
            raise HTTPException(404, "ticket not found")
        msgs = (
            await s.scalars(
                select(DiscordMessageCache)
                .where(DiscordMessageCache.channel_id == ticket.thread_id)
                .order_by(DiscordMessageCache.created_at.asc())
            )
        ).all()
    return _render(request, "ticket_detail.html", user=user, ticket=ticket, messages=msgs)


# -------------------- web music API + page ------------------------------

@router.get("/api/v1/music/{server_id}/state")
async def music_state_api(
    server_id: int,
    access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE),
):
    await _require_user(access_token)
    from bot.services.audio_player import get_manager
    mgr = get_manager()
    p = mgr.get_existing(server_id) if hasattr(mgr, "get_existing") else None
    if p is None:
        return {"connected": False, "current": None, "queue": [], "volume": 1.0, "loop": "off", "paused": False}
    return p.snapshot()


@router.post("/api/v1/music/{server_id}/play")
async def music_play_api(
    server_id: int,
    request: Request,
    access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE),
):
    user = await _require_user(access_token)
    body = await request.json()
    query = (body.get("query") or "").strip()
    if not query:
        raise HTTPException(400, "missing query")
    bot = get_bot()
    if bot is None:
        raise HTTPException(503, "bot offline")
    guild = bot.get_guild(server_id)
    if guild is None:
        raise HTTPException(404, "guild")
    from bot.services.audio_player import get_manager, search_tracks
    tracks = await search_tracks(query, requested_by=user.username)
    if not tracks:
        raise HTTPException(404, "no results")
    mgr = get_manager()
    player = mgr.get(bot, server_id)
    for t in tracks:
        player.add(t)
    await player.ensure_loop()
    return {"queued": len(tracks)}


@router.post("/api/v1/music/{server_id}/{action}")
async def music_action_api(
    server_id: int,
    action: str,
    request: Request,
    access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE),
):
    await _require_user(access_token)
    from bot.services.audio_player import get_manager
    mgr = get_manager()
    p = mgr.get_existing(server_id)
    if p is None:
        raise HTTPException(404, "no player")
    if action == "pause":
        await p.pause()
    elif action == "resume":
        await p.resume()
    elif action == "skip":
        await p.skip()
    elif action == "stop":
        await p.stop()
    elif action == "volume":
        body = await request.json()
        pct = int(body.get("percent", 100))
        p.set_volume(max(0, min(200, pct)) / 100.0)
    elif action == "loop":
        body = await request.json()
        mode = str(body.get("mode", "off"))
        if mode in ("off", "track", "queue"):
            p.loop = mode
    elif action == "shuffle":
        p.shuffle()
    else:
        raise HTTPException(400, "unknown action")
    return {"ok": True}


@router.get("/api/v1/music/{server_id}/playlists")
async def music_playlists_api(
    server_id: int,
    access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE),
):
    await _require_user(access_token)
    async with db_session() as s:
        rows = (
            await s.scalars(
                select(MusicPlaylist).where(MusicPlaylist.server_id == server_id).order_by(MusicPlaylist.name)
            )
        ).all()
    return [{"id": str(r.id), "name": r.name, "tracks": r.tracks} for r in rows]

@router.get("/api/v1/user-settings/me")
async def user_settings_me(
    access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE),
):
    user = await _current_user(access_token)
    if user is None:
        return {"theme": "dark", "accent_color": "#60A5FA", "font_size": "medium"}
    async with db_session() as s:
        row = await s.get(WebUserSettings, user.id)
    if row is None:
        return {"theme": "dark", "accent_color": "#60A5FA", "font_size": "medium"}
    return {"theme": row.theme, "accent_color": row.accent_color, "font_size": row.font_size}
