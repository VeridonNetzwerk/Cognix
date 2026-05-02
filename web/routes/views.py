"""Server-rendered HTML views (Jinja2 dashboard).

This is the primary user-facing surface. It uses the same DB models as the
JSON API and reuses ``auth_service`` for login. Authentication is via the
``cognix_access`` HttpOnly cookie set by the JSON ``/api/v1/auth/login``
endpoint, but we also accept HTML form posts here for ergonomics.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Cookie, Form, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import desc, func, select

from bot.runtime import get_bot, get_bot_info
from config.constants import (
    AUDIT_LOGOUT,
    AUDIT_USER_CREATED,
    AUDIT_USER_DELETED,
    AUDIT_USER_UPDATED,
)
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
        cogs_count = (await s.scalar(
            select(func.count(CogState.id)).where(CogState.enabled.is_(True))
        )) or 0
        open_tickets = (await s.scalar(
            select(func.count(Ticket.id)).where(Ticket.status == TicketStatus.OPEN)
        )) or 0
        recent = (await s.scalars(
            select(AuditLog).order_by(desc(AuditLog.created_at)).limit(8)
        )).all()
        from web.security.permissions import has_permission as _hp
        can_servers_write = await _hp(s, user, "servers", level="write")

    # BUG #2 fix: dedup users across guilds via member set
    bot = get_bot()
    if bot is not None:
        unique_ids: set[int] = set()
        for g in bot.guilds:
            for m in g.members:
                unique_ids.add(m.id)
        users_count = len(unique_ids)
        # If member cache is empty (intent disabled / not yet populated), fall back to summed counts but de-dup is best-effort.
        if users_count == 0:
            users_count = sum(g.member_count or 0 for g in bot.guilds)
    else:
        async with db_session() as s2:
            users_count = (await s2.scalar(
                select(func.coalesce(func.sum(Server.member_count), 0))
            )) or 0

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
        "user_count": users_count,
        "version": info["version"],
    }
    return _render(request, "dashboard.html", user=user, metrics=metrics, recent_audit=recent,
                   can_servers_write=can_servers_write)


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
        pass  # silent â€” surface via bot logs
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
    async with db_session() as s:
        servers = (await s.scalars(select(Server).order_by(Server.name))).all()
    servers_json = json.dumps(
        [{"id": str(srv.id), "name": srv.name} for srv in servers]
    )
    return _render(request, "music.html", user=user, servers_json=servers_json)


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


# FEAT #3: dedicated archive + settings sub-routes for the tickets section.

@router.get("/tickets/archive", response_class=HTMLResponse)
async def tickets_archive(request: Request,
                          access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE)) -> HTMLResponse:
    user = await _require_user(access_token)
    async with db_session() as s:
        tickets = (await s.scalars(
            select(Ticket)
            .where(Ticket.status.in_([TicketStatus.CLOSED, TicketStatus.ARCHIVED]))
            .order_by(desc(Ticket.created_at))
            .limit(500)
        )).all()
        servers = (await s.scalars(select(Server).order_by(Server.name))).all()
    return _render(
        request,
        "tickets.html",
        user=user,
        tickets=tickets,
        servers=servers,
        status_filter="archived",
        archive_view=True,
    )


@router.get("/tickets/settings", response_class=HTMLResponse)
async def tickets_settings(request: Request,
                            access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE)) -> HTMLResponse:
    user = await _require_user(access_token)
    async with db_session() as s:
        servers = (await s.scalars(select(Server).order_by(Server.name))).all()
        configs = (await s.scalars(select(ServerConfig))).all()
    cfg_by_server = {c.server_id: c for c in configs}
    return _render(
        request,
        "ticket_settings.html",
        user=user,
        servers=servers,
        cfg_by_server=cfg_by_server,
    )


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
    server_lookup = {sv.id: sv.name for sv in servers}
    return _render(
        request,
        "discord_log.html",
        user=me,
        events=rows,
        servers=servers,
        server_lookup=server_lookup,
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
        # Per-user permission map for the edit panel
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
    """FEAT #6: save per-module permission matrix for a web user."""
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


# ============================================================================
# Phase 3: giveaways, members, combined log, ticket types/panels, server events
# ============================================================================

from database.models.giveaway import Giveaway, GiveawayStatus  # noqa: E402
from database.models.server_event_config import ServerEventConfig  # noqa: E402
from database.models.ticket_panel import TicketPanel, TicketType  # noqa: E402
from database.models.embed_template import EmbedTemplate  # noqa: E402


# ---------- Giveaways -------------------------------------------------------

@router.get("/giveaways", response_class=HTMLResponse)
async def giveaways_view(request: Request,
                         access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE)) -> HTMLResponse:
    user = await _require_user(access_token)
    async with db_session() as s:
        rows = (
            await s.scalars(
                select(Giveaway).order_by(desc(Giveaway.created_at)).limit(200)
            )
        ).all()
        servers = (await s.scalars(select(Server).order_by(Server.name))).all()
    return _render(request, "giveaways.html", user=user, giveaways=rows, servers=servers)


@router.get("/giveaways/{giveaway_id}", response_class=HTMLResponse)
async def giveaway_detail_view(
    giveaway_id: str,
    request: Request,
    access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE),
) -> HTMLResponse:
    """FEAT #5: dedicated giveaway detail view with live countdown."""
    user = await _require_user(access_token)
    try:
        gid = uuid.UUID(giveaway_id)
    except ValueError as exc:
        raise HTTPException(404) from exc
    async with db_session() as s:
        g = await s.get(Giveaway, gid)
        if g is None:
            raise HTTPException(404)
        server = await s.get(Server, g.server_id)
    return _render(
        request,
        "giveaway_detail.html",
        user=user,
        g=g,
        server=server,
    )


@router.post("/giveaways/{giveaway_id}/end")
async def giveaways_end(giveaway_id: str,
                         access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE)) -> Response:
    user = await _require_user(access_token)
    async with db_session() as s:
        g = await s.get(Giveaway, uuid.UUID(giveaway_id))
        if g is None:
            raise HTTPException(404)
        g.ended = True
        g.status = GiveawayStatus.ENDED
        s.add(AuditLog(actor_id=user.id, action="giveaway.end", target=str(g.id)))
    bot = get_bot()
    if bot is not None:
        cog = bot.get_cog("Giveaways")
        if cog is not None:
            try:
                await cog._end_giveaway(uuid.UUID(giveaway_id))  # type: ignore[attr-defined]
            except Exception:
                pass
    return RedirectResponse("/giveaways", status_code=303)


@router.post("/giveaways/{giveaway_id}/delete")
async def giveaways_delete(giveaway_id: str,
                           access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE)) -> Response:
    user = await _require_user(access_token)
    async with db_session() as s:
        g = await s.get(Giveaway, uuid.UUID(giveaway_id))
        if g is not None:
            s.add(AuditLog(actor_id=user.id, action="giveaway.delete", target=str(g.id)))
            await s.delete(g)
    return RedirectResponse("/giveaways", status_code=303)


# FEAT #6: Giveaway management actions invoked from the dashboard.

@router.post("/giveaways/{giveaway_id}/reroll")
async def giveaways_reroll(giveaway_id: str,
                            access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE)) -> Response:
    user = await _require_user(access_token)
    async with db_session() as s:
        g = await s.get(Giveaway, uuid.UUID(giveaway_id))
        if g is None:
            raise HTTPException(404)
        s.add(AuditLog(actor_id=user.id, action="giveaway.reroll", target=str(g.id)))
    bot = get_bot()
    if bot is not None:
        cog = bot.get_cog("Giveaways")
        if cog is not None:
            try:
                async with db_session() as s2:
                    g2 = await s2.get(Giveaway, uuid.UUID(giveaway_id))
                    channel = bot.get_channel(g2.channel_id) if g2 else None
                    if g2 is not None and channel is not None:
                        winners = await cog._draw_winners(g2, channel)  # type: ignore[attr-defined]
                        g2.winners = winners
                        if winners:
                            try:
                                mentions = ", ".join(f"<@{w}>" for w in winners)
                                await channel.send(
                                    f"\N{PARTY POPPER} New winners for **{g2.prize}**: {mentions}"
                                )
                            except Exception:
                                pass
            except Exception:
                pass
    return RedirectResponse(f"/giveaways/{giveaway_id}", status_code=303)


@router.post("/giveaways/{giveaway_id}/extend")
async def giveaways_extend(giveaway_id: str,
                            additional_seconds: int = Form(...),
                            access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE)) -> Response:
    user = await _require_user(access_token)
    extra = max(60, min(60 * 60 * 24 * 30, int(additional_seconds)))
    from datetime import timedelta as _td
    async with db_session() as s:
        g = await s.get(Giveaway, uuid.UUID(giveaway_id))
        if g is None:
            raise HTTPException(404)
        if g.ended:
            g.ended = False
            g.status = GiveawayStatus.ACTIVE
        g.ends_at = g.ends_at + _td(seconds=extra)
        s.add(AuditLog(actor_id=user.id, action="giveaway.extend",
                       target=str(g.id), details={"seconds": extra}))
    return RedirectResponse(f"/giveaways/{giveaway_id}", status_code=303)


@router.post("/giveaways/{giveaway_id}/edit")
async def giveaways_edit(giveaway_id: str,
                          prize: str = Form(...),
                          winner_count: int = Form(...),
                          access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE)) -> Response:
    user = await _require_user(access_token)
    prize = (prize or "").strip()[:256]
    if not prize:
        raise HTTPException(400, "prize required")
    wc = max(1, min(50, int(winner_count)))
    async with db_session() as s:
        g = await s.get(Giveaway, uuid.UUID(giveaway_id))
        if g is None:
            raise HTTPException(404)
        g.prize = prize
        g.winner_count = wc
        s.add(AuditLog(actor_id=user.id, action="giveaway.edit", target=str(g.id)))
    return RedirectResponse(f"/giveaways/{giveaway_id}", status_code=303)


# ---------- Members (per-server live view) ---------------------------------

@router.get("/members", response_class=HTMLResponse)
async def members_view(request: Request,
                       server_id: str | None = None,
                       q: str = "",
                       access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE)) -> HTMLResponse:
    user = await _require_user(access_token)
    async with db_session() as s:
        servers = (await s.scalars(select(Server).order_by(Server.name))).all()
    members: list[dict[str, Any]] = []
    selected: int | None = None
    bot = get_bot()
    if server_id and bot is not None:
        try:
            sid = int(server_id)
        except ValueError:
            sid = 0
        guild = bot.get_guild(sid) if sid else None
        if guild is not None:
            selected = guild.id
            ql = (q or "").strip().lower()
            for m in guild.members:
                if ql and ql not in m.name.lower() and ql not in str(m.id):
                    continue
                members.append({
                    "id": m.id,
                    "name": m.name,
                    "display_name": m.display_name,
                    "discriminator": m.discriminator,
                    "joined_at": m.joined_at.isoformat() if m.joined_at else "",
                    "roles": [{"id": r.id, "name": r.name, "color": r.colour.value} for r in m.roles if not r.is_default()],
                    "bot": m.bot,
                    "avatar": m.display_avatar.url if m.display_avatar else "",
                })
                if len(members) >= 500:
                    break
    return _render(
        request, "members.html", user=user, servers=servers,
        members=members, selected_server_id=selected, query=q,
    )


@router.post("/members/{server_id}/{member_id}/kick")
async def members_kick(server_id: str, member_id: str, reason: str = Form(default=""),
                       access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE)) -> Response:
    user = await _require_user(access_token)
    bot = get_bot()
    if bot is not None:
        guild = bot.get_guild(int(server_id))
        if guild is not None:
            member = guild.get_member(int(member_id))
            if member is not None:
                try:
                    await member.kick(reason=f"web by {user.username}: {reason}")
                except Exception:
                    pass
    async with db_session() as s:
        s.add(AuditLog(actor_id=user.id, action="member.kick", target=member_id))
    return RedirectResponse(f"/members?server_id={server_id}", status_code=303)


@router.post("/members/{server_id}/{member_id}/ban")
async def members_ban(server_id: str, member_id: str, reason: str = Form(default=""),
                      access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE)) -> Response:
    user = await _require_user(access_token)
    bot = get_bot()
    if bot is not None:
        guild = bot.get_guild(int(server_id))
        if guild is not None:
            try:
                await guild.ban(discord_obj_for(int(member_id)), reason=f"web by {user.username}: {reason}")
            except Exception:
                pass
    async with db_session() as s:
        s.add(AuditLog(actor_id=user.id, action="member.ban", target=member_id))
    return RedirectResponse(f"/members?server_id={server_id}", status_code=303)


def discord_obj_for(user_id: int) -> Any:
    import discord as _d
    return _d.Object(id=user_id)


# ---------- Combined log view (FEAT #9) -----------------------------------

@router.get("/log", response_class=HTMLResponse)
async def log_view(request: Request, tab: str = "web",
                   access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE)) -> HTMLResponse:
    user = await _require_user(access_token)
    if tab not in ("web", "discord"):
        tab = "web"
    web_rows: list[Any] = []
    discord_rows: list[Any] = []
    actor_names: dict[str, str] = {}
    async with db_session() as s:
        if tab == "web":
            web_rows = (await s.scalars(
                select(AuditLog).order_by(desc(AuditLog.created_at)).limit(200)
            )).all()
            actor_ids = {r.actor_id for r in web_rows if r.actor_id is not None}
            if actor_ids:
                users = (await s.scalars(
                    select(WebUser).where(WebUser.id.in_(actor_ids))
                )).all()
                actor_names = {str(u.id): u.username for u in users}
        else:
            discord_rows = (await s.scalars(
                select(DiscordEvent).order_by(desc(DiscordEvent.created_at)).limit(200)
            )).all()
    return _render(
        request, "log.html", user=user, tab=tab, web_rows=web_rows,
        discord_rows=discord_rows, actor_names=actor_names,
    )


# ---------- Ticket types & panels (FEAT #6) -------------------------------

@router.get("/ticket-types", response_class=HTMLResponse)
async def ticket_types_view(request: Request,
                            access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE)) -> HTMLResponse:
    user = await _require_user(access_token)
    async with db_session() as s:
        types = (await s.scalars(select(TicketType).order_by(TicketType.created_at))).all()
        servers = (await s.scalars(select(Server).order_by(Server.name))).all()
    return _render(request, "ticket_types.html", user=user, types=types, servers=servers)


@router.post("/ticket-types/create")
async def ticket_types_create(server_id: int = Form(...), name: str = Form(...),
                              description: str = Form(default=""), emoji: str = Form(default=""),
                              category_id: str = Form(default=""), ping_role_id: str = Form(default=""),
                              access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE)) -> Response:
    user = await _require_user(access_token)
    async with db_session() as s:
        t = TicketType(
            server_id=int(server_id), name=name[:64], description=description[:256],
            emoji=emoji[:16],
            category_id=int(category_id) if category_id.strip().isdigit() else None,
            ping_role_id=int(ping_role_id) if ping_role_id.strip().isdigit() else None,
            welcome_embed={},
        )
        s.add(t)
        s.add(AuditLog(actor_id=user.id, action="ticket_type.create", target=name))
    return RedirectResponse("/ticket-types", status_code=303)


@router.post("/ticket-types/{type_id}/delete")
async def ticket_types_delete(type_id: str,
                              access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE)) -> Response:
    user = await _require_user(access_token)
    async with db_session() as s:
        t = await s.get(TicketType, uuid.UUID(type_id))
        if t is not None:
            s.add(AuditLog(actor_id=user.id, action="ticket_type.delete", target=t.name))
            await s.delete(t)
    return RedirectResponse("/ticket-types", status_code=303)


@router.get("/ticket-panels", response_class=HTMLResponse)
async def ticket_panels_view(request: Request,
                             access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE)) -> HTMLResponse:
    user = await _require_user(access_token)
    async with db_session() as s:
        panels = (await s.scalars(select(TicketPanel).order_by(TicketPanel.created_at))).all()
        types = (await s.scalars(select(TicketType).order_by(TicketType.name))).all()
        servers = (await s.scalars(select(Server).order_by(Server.name))).all()
    return _render(request, "ticket_panels.html", user=user, panels=panels, types=types, servers=servers)


@router.post("/ticket-panels/create")
async def ticket_panels_create(server_id: int = Form(...), name: str = Form(...),
                               access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE)) -> Response:
    user = await _require_user(access_token)
    async with db_session() as s:
        p = TicketPanel(server_id=int(server_id), name=name[:64], embed={}, buttons=[])
        s.add(p)
        s.add(AuditLog(actor_id=user.id, action="ticket_panel.create", target=name))
    return RedirectResponse("/ticket-panels", status_code=303)


@router.post("/ticket-panels/{panel_id}/delete")
async def ticket_panels_delete(panel_id: str,
                               access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE)) -> Response:
    user = await _require_user(access_token)
    async with db_session() as s:
        p = await s.get(TicketPanel, uuid.UUID(panel_id))
        if p is not None:
            s.add(AuditLog(actor_id=user.id, action="ticket_panel.delete", target=p.name))
            await s.delete(p)
    return RedirectResponse("/ticket-panels", status_code=303)


# ---------- Welcome / leave / boost (FEAT #4) ------------------------------

@router.get("/welcome", response_class=HTMLResponse)
async def welcome_view(request: Request, server_id: int | None = None,
                       access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE)) -> HTMLResponse:
    user = await _require_user(access_token)
    async with db_session() as s:
        servers = (await s.scalars(select(Server).order_by(Server.name))).all()
        cfg: ServerEventConfig | None = None
        if server_id:
            cfg = await s.get(ServerEventConfig, int(server_id))
    return _render(
        request, "welcome.html", user=user, servers=servers, cfg=cfg,
        selected_server_id=server_id,
    )


@router.post("/welcome/save")
async def welcome_save(
    server_id: int = Form(...),
    join_enabled: str = Form(default=""),
    join_channel_id: str = Form(default=""),
    join_title: str = Form(default=""),
    join_description: str = Form(default=""),
    join_color: str = Form(default="#60a5fa"),
    leave_enabled: str = Form(default=""),
    leave_channel_id: str = Form(default=""),
    leave_title: str = Form(default=""),
    leave_description: str = Form(default=""),
    leave_color: str = Form(default="#f43f5e"),
    boost_enabled: str = Form(default=""),
    boost_channel_id: str = Form(default=""),
    boost_title: str = Form(default=""),
    boost_description: str = Form(default=""),
    boost_color: str = Form(default="#a855f7"),
    access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE),
) -> Response:
    user = await _require_user(access_token)

    def _hex_to_int(h: str, fallback: int) -> int:
        try:
            return int(h.lstrip("#"), 16)
        except ValueError:
            return fallback

    def _bool(v: str) -> bool:
        return v.lower() in ("on", "true", "1", "yes")

    def _ch(v: str) -> int | None:
        return int(v) if v.strip().isdigit() else None

    async with db_session() as s:
        cfg = await s.get(ServerEventConfig, int(server_id))
        if cfg is None:
            cfg = ServerEventConfig(server_id=int(server_id),
                                    join_embed={}, leave_embed={}, boost_embed={})
            s.add(cfg)
        cfg.join_enabled = _bool(join_enabled)
        cfg.join_channel_id = _ch(join_channel_id)
        cfg.join_embed = {
            "title": join_title, "description": join_description,
            "color": _hex_to_int(join_color, 0x60A5FA),
        }
        cfg.leave_enabled = _bool(leave_enabled)
        cfg.leave_channel_id = _ch(leave_channel_id)
        cfg.leave_embed = {
            "title": leave_title, "description": leave_description,
            "color": _hex_to_int(leave_color, 0xF43F5E),
        }
        cfg.boost_enabled = _bool(boost_enabled)
        cfg.boost_channel_id = _ch(boost_channel_id)
        cfg.boost_embed = {
            "title": boost_title, "description": boost_description,
            "color": _hex_to_int(boost_color, 0xA855F7),
        }
        s.add(AuditLog(actor_id=user.id, action="welcome.save", target=str(server_id)))
    return RedirectResponse(f"/welcome?server_id={server_id}", status_code=303)


# ---------- Info-embed editor (FEAT #7) -----------------------------------

@router.post("/info-embed/save")
async def info_embed_save(server_id: int = Form(...), name: str = Form("info"),
                          title: str = Form(default=""), description: str = Form(default=""),
                          color: str = Form(default="#60a5fa"),
                          access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE)) -> Response:
    user = await _require_user(access_token)
    try:
        color_int = int(color.lstrip("#"), 16)
    except ValueError:
        color_int = 0x60A5FA
    async with db_session() as s:
        existing = await s.scalar(
            select(EmbedTemplate).where(
                EmbedTemplate.server_id == int(server_id),
                EmbedTemplate.key == name,
            )
        )
        if existing is None:
            s.add(EmbedTemplate(
                server_id=int(server_id), key=name[:64],
                title=title[:256], description=description, color=color_int,
            ))
        else:
            existing.title = title[:256]
            existing.description = description
            existing.color = color_int
        s.add(AuditLog(actor_id=user.id, action="info_embed.save", target=name))
    return RedirectResponse(f"/embeds", status_code=303)


# ---------- Bot lifecycle (FEAT #2) ---------------------------------------

@router.post("/api/v1/bot/lifecycle/{action}")
async def bot_lifecycle(action: str,
                        access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE)) -> dict:
    user = await _require_user(access_token)
    if user.role != WebRole.ADMIN:
        raise HTTPException(403)
    from bot.runtime import (
        request_bot_restart as _rr,
        request_bot_start as _rs,
        request_bot_stop as _rt,
    )
    if action == "start":
        _rs()
    elif action == "stop":
        await _rt()
    elif action == "restart":
        await _rr()
    else:
        raise HTTPException(400, "unknown action")
    async with db_session() as s:
        s.add(AuditLog(actor_id=user.id, action=f"bot.{action}", target=""))
    return {"ok": True, "action": action}




# ---------- Invite Tracker (FEAT #8) ----------------------------------------

from database.models.invite_stats import InviteStats  # noqa: E402
from database.models.invite_uses import InviteUse  # noqa: E402


@router.get("/invites", response_class=HTMLResponse)
async def invites_view(
    request: Request,
    server_id: str | None = None,
    access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE),
) -> HTMLResponse:
    """FEAT #8: dashboard tab for invite tracker stats."""
    user = await _require_user(access_token)
    rows = []
    recent = []
    servers = []
    invite_error: str | None = None
    leaderboard: list[dict[str, Any]] = []
    try:
        async with db_session() as s:
            servers = (await s.scalars(select(Server).order_by(Server.name))).all()
            if server_id and server_id.isdigit():
                # per-server view: show raw rows so per-invite breakdown is
                # visible.
                stmt = (
                    select(InviteStats)
                    .where(InviteStats.server_id == int(server_id))
                    .order_by(desc(InviteStats.active_uses))
                    .limit(200)
                )
                rows = (await s.scalars(stmt)).all()
                for r in rows:
                    leaderboard.append({
                        "inviter_id": r.inviter_id,
                        "active_uses": r.active_uses,
                        "total_uses": r.total_uses,
                        "left_uses": r.left_uses,
                        "fake_uses": r.fake_uses,
                    })
            else:
                # BUG #6: when aggregating across all servers, dedup users by
                # inviter_id and sum their counters so a single user with
                # invites in multiple guilds does not appear multiple times.
                stmt = (
                    select(
                        InviteStats.inviter_id,
                        func.coalesce(func.sum(InviteStats.active_uses), 0).label("active_uses"),
                        func.coalesce(func.sum(InviteStats.total_uses), 0).label("total_uses"),
                        func.coalesce(func.sum(InviteStats.left_uses), 0).label("left_uses"),
                        func.coalesce(func.sum(InviteStats.fake_uses), 0).label("fake_uses"),
                    )
                    .group_by(InviteStats.inviter_id)
                    .order_by(desc(func.sum(InviteStats.active_uses)))
                    .limit(200)
                )
                agg = (await s.execute(stmt)).all()
                rows = []  # not used in aggregate mode
                for r in agg:
                    leaderboard.append({
                        "inviter_id": r.inviter_id,
                        "active_uses": int(r.active_uses or 0),
                        "total_uses": int(r.total_uses or 0),
                        "left_uses": int(r.left_uses or 0),
                        "fake_uses": int(r.fake_uses or 0),
                    })
            recent_stmt = select(InviteUse).order_by(desc(InviteUse.created_at)).limit(50)
            if server_id:
                try:
                    recent_stmt = recent_stmt.where(InviteUse.server_id == int(server_id))
                except ValueError:
                    pass
            recent = (await s.scalars(recent_stmt)).all()
    except Exception as exc:  # noqa: BLE001
        invite_error = f"Invite-Daten konnten nicht geladen werden: {exc}"
        try:
            async with db_session() as s:
                servers = (await s.scalars(select(Server).order_by(Server.name))).all()
        except Exception:  # noqa: BLE001
            servers = []
    # Resolve display names from bot cache
    bot = get_bot()
    user_names: dict[int, str] = {}
    if bot is not None:
        for r in leaderboard:
            uid = r["inviter_id"]
            if uid and uid not in user_names:
                u = bot.get_user(uid)
                user_names[uid] = u.display_name if u else f"<@{uid}>"
        for r in recent:
            for uid in (r.inviter_id, r.invitee_id):
                if uid and uid not in user_names:
                    u = bot.get_user(uid)
                    user_names[uid] = u.display_name if u else f"<@{uid}>"
    return _render(
        request,
        "invites.html",
        user=user,
        servers=servers,
        stats=leaderboard,
        recent=recent,
        user_names=user_names,
        invite_error=invite_error,
        selected_server_id=int(server_id) if server_id and server_id.isdigit() else None,
    )


# ---- FEAT #7: extended member actions (timeout/mute/deafen/dm) -----------

@router.post("/members/{server_id}/{member_id}/timeout")
async def members_timeout(server_id: str, member_id: str,
                           minutes: int = Form(default=10),
                           reason: str = Form(default=""),
                           access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE)) -> Response:
    import discord as _d
    me = await _require_user(access_token)
    bot = get_bot()
    if bot is not None:
        guild = bot.get_guild(int(server_id))
        if guild is not None:
            member = guild.get_member(int(member_id))
            if member is not None:
                try:
                    until = _dt2.now(tz=_tz2.utc) + __import__('datetime').timedelta(minutes=max(1, min(40320, minutes)))
                    await member.edit(timed_out_until=until, reason=f"web by {me.username}: {reason}")
                except Exception:
                    pass
    async with db_session() as s:
        s.add(AuditLog(actor_id=me.id, action="member.timeout", target=member_id,
                       details={"minutes": minutes, "reason": reason}))
    return RedirectResponse(f"/members?server_id={server_id}", status_code=303)


@router.post("/members/{server_id}/{member_id}/mute")
async def members_mute(server_id: str, member_id: str,
                        muted: str = Form(default="1"),
                        access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE)) -> Response:
    me = await _require_user(access_token)
    bot = get_bot()
    flag = muted not in ("0", "false", "no", "")
    if bot is not None:
        guild = bot.get_guild(int(server_id))
        if guild is not None:
            member = guild.get_member(int(member_id))
            if member is not None and member.voice is not None:
                try:
                    await member.edit(mute=flag, reason=f"web by {me.username}")
                except Exception:
                    pass
    async with db_session() as s:
        s.add(AuditLog(actor_id=me.id, action="member.mute", target=member_id, details={"mute": flag}))
    return RedirectResponse(f"/members?server_id={server_id}", status_code=303)


@router.post("/members/{server_id}/{member_id}/deafen")
async def members_deafen(server_id: str, member_id: str,
                          deafened: str = Form(default="1"),
                          access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE)) -> Response:
    me = await _require_user(access_token)
    bot = get_bot()
    flag = deafened not in ("0", "false", "no", "")
    if bot is not None:
        guild = bot.get_guild(int(server_id))
        if guild is not None:
            member = guild.get_member(int(member_id))
            if member is not None and member.voice is not None:
                try:
                    await member.edit(deafen=flag, reason=f"web by {me.username}")
                except Exception:
                    pass
    async with db_session() as s:
        s.add(AuditLog(actor_id=me.id, action="member.deafen", target=member_id, details={"deafen": flag}))
    return RedirectResponse(f"/members?server_id={server_id}", status_code=303)


@router.post("/members/{server_id}/{member_id}/dm")
async def members_dm(server_id: str, member_id: str,
                      message: str = Form(...),
                      access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE)) -> Response:
    me = await _require_user(access_token)
    bot = get_bot()
    if bot is not None and message.strip():
        try:
            user_obj = bot.get_user(int(member_id)) or await bot.fetch_user(int(member_id))
            if user_obj is not None:
                await user_obj.send(message[:1900])
        except Exception:
            pass
    async with db_session() as s:
        s.add(AuditLog(actor_id=me.id, action="member.dm", target=member_id,
                       details={"length": len(message)}))
    return RedirectResponse(f"/members?server_id={server_id}", status_code=303)

# ============================================================================
# BUG #7 - Channel/Roles dropdown API
# ============================================================================

@router.get("/api/v1/servers/{guild_id}/channels")
async def api_server_channels(
    guild_id: int,
    access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE),
) -> dict:
    """Return all channels of a guild grouped by category for dashboard dropdowns."""
    await _require_user(access_token)
    import discord as _d
    bot = get_bot()
    if bot is None:
        return {"channels": [], "error": "bot_offline"}
    guild = bot.get_guild(int(guild_id))
    if guild is None:
        raise HTTPException(404, "guild not found")
    out: list[dict[str, Any]] = []
    for ch in sorted(guild.channels, key=lambda c: (c.position, c.id)):
        if isinstance(ch, _d.CategoryChannel):
            kind = "category"
        elif isinstance(ch, _d.VoiceChannel):
            kind = "voice"
        elif isinstance(ch, _d.StageChannel):
            kind = "stage"
        elif isinstance(ch, _d.ForumChannel):
            kind = "forum"
        else:
            kind = "text"
        cat = getattr(ch, "category", None)
        out.append({
            "id": str(ch.id),
            "name": ch.name,
            "type": kind,
            "category_id": str(cat.id) if cat else None,
            "category_name": cat.name if cat else None,
        })
    return {"channels": out}


@router.get("/api/v1/servers/{guild_id}/roles")
async def api_server_roles(
    guild_id: int,
    access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE),
) -> dict:
    """Return all roles for a guild - used by giveaway create form etc."""
    await _require_user(access_token)
    bot = get_bot()
    if bot is None:
        return {"roles": [], "error": "bot_offline"}
    guild = bot.get_guild(int(guild_id))
    if guild is None:
        raise HTTPException(404, "guild not found")
    out: list[dict[str, Any]] = []
    for r in sorted(guild.roles, key=lambda r: -r.position):
        if r.is_default():
            continue
        out.append({
            "id": str(r.id),
            "name": r.name,
            "color": f"#{r.color.value:06x}" if r.color and r.color.value else "#99aab5",
            "member_count": len(r.members),
            "managed": r.managed,
        })
    return {"roles": out}


# ============================================================================
# BUG #5 - Per-role permission toggles (used by Server detail page)
# ============================================================================

_ROLE_PERMISSION_KEYS = (
    "tickets_create",
    "tickets_close",
    "giveaways_start",
    "backup_create",
    "moderation_use",
    "music_use",
)


@router.get("/api/v1/servers/{guild_id}/roles/{role_id}/permissions")
async def api_role_permissions_get(
    guild_id: int,
    role_id: int,
    access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE),
) -> dict:
    await _require_user(access_token)
    perms: dict[str, bool] = {k: False for k in _ROLE_PERMISSION_KEYS}
    async with db_session() as s:
        rows = (
            await s.scalars(
                select(RolePermission)
                .where(RolePermission.server_id == int(guild_id))
                .where(RolePermission.discord_role_id == int(role_id))
            )
        ).all()
        for r in rows:
            if r.command in perms:
                perms[r.command] = bool(r.allowed)
    return {"role_id": str(role_id), "permissions": perms}


@router.post("/api/v1/servers/{guild_id}/roles/{role_id}/permissions")
async def api_role_permissions_set(
    guild_id: int,
    role_id: int,
    payload: dict,
    access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE),
) -> dict:
    me = await _require_user(access_token)
    perms_in = payload.get("permissions") or {}
    if not isinstance(perms_in, dict):
        raise HTTPException(400, "permissions must be an object")
    async with db_session() as s:
        for key in _ROLE_PERMISSION_KEYS:
            value = bool(perms_in.get(key))
            row = await s.scalar(
                select(RolePermission)
                .where(RolePermission.server_id == int(guild_id))
                .where(RolePermission.discord_role_id == int(role_id))
                .where(RolePermission.command == key)
            )
            if row is None:
                s.add(RolePermission(
                    server_id=int(guild_id),
                    discord_role_id=int(role_id),
                    command=key,
                    allowed=value,
                ))
            else:
                row.allowed = value
        s.add(AuditLog(actor_id=me.id, action="role.permissions",
                       target=str(role_id), details={"server_id": str(guild_id)}))
    return {"ok": True}


# ============================================================================
# FEAT #4 - Create a giveaway from the dashboard
# ============================================================================

@router.post("/giveaways/create")
async def giveaways_create(
    request: Request,
    server_id: str = Form(...),
    channel_id: str = Form(...),
    prize: str = Form(...),
    winners: int = Form(default=1),
    duration: str = Form(...),
    required_role_id: str | None = Form(default=None),
    access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE),
) -> Response:
    me = await _require_user(access_token)
    prize = (prize or "").strip()[:256]
    if not prize:
        raise HTTPException(400, "prize required")
    bot = get_bot()
    if bot is None:
        raise HTTPException(503, "bot offline")
    from bot.cogs.giveaway import _parse_duration, _build_embed, PARTY
    delta = _parse_duration(duration)
    if delta is None:
        raise HTTPException(400, "invalid duration (use e.g. 30m, 2h, 1d)")
    import discord as _d
    from datetime import datetime as _dt, timezone as _tz
    guild = bot.get_guild(int(server_id))
    if guild is None:
        raise HTTPException(404, "guild not found")
    channel = guild.get_channel(int(channel_id))
    if not isinstance(channel, _d.TextChannel):
        raise HTTPException(400, "channel must be a text channel")
    role_id_int: int | None = None
    if required_role_id and str(required_role_id).strip().isdigit():
        role_id_int = int(required_role_id)
    ends_at = _dt.now(tz=_tz.utc) + delta
    g = Giveaway(
        server_id=guild.id,
        channel_id=channel.id,
        message_id=0,
        prize=prize,
        winner_count=max(1, min(50, int(winners))),
        ends_at=ends_at,
        host_id=int(getattr(bot.user, "id", 0) or 0),
        required_role_id=role_id_int,
        winners=[],
    )
    try:
        msg = await channel.send(embed=_build_embed(g))
        await msg.add_reaction(PARTY)
    except _d.HTTPException as exc:
        raise HTTPException(400, f"discord error: {exc}") from exc
    g.message_id = msg.id
    async with db_session() as s:
        s.add(g)
        await s.flush()
        new_id = g.id
        s.add(AuditLog(actor_id=me.id, action="giveaway.create", target=str(new_id),
                       details={"prize": prize, "channel_id": str(channel.id)}))
    return RedirectResponse(f"/giveaways/{new_id}", status_code=303)


# ============================================================================
# FEAT #6 - Admin can reset OTP / 2FA of any other user
# ============================================================================

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