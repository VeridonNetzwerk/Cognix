"""Cogs management and marketplace routes."""

from __future__ import annotations

from datetime import UTC
from datetime import datetime as _dt

from fastapi import Cookie, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select

from bot.runtime import get_bot
from bot.database.models.cogs.cog_state import CogState
from bot.database.models.server.server import Server
from bot.database.models.server.server_cog_state import ServerCogState
from bot.database.models.auth.web_user import WebRole
from bot.database.session import db_session
from web.deps import ACCESS_COOKIE
from bot.pages._shared import _render, _require_user, router


@router.get("/cogs", response_class=HTMLResponse)
async def cogs_view(request: Request,
                    access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE)) -> HTMLResponse:
    user = await _require_user(access_token)

    from bot.cogs.registry import get_all_cog_info, get_loaded_cogs

    loaded_modules = set(get_loaded_cogs())
    bot = get_bot()
    if bot is not None:
        loaded_modules |= set(bot.extensions.keys())

    all_cog_info = get_all_cog_info()
    loaded_cog_infos = [
        info for info in all_cog_info
        if info["module"] in loaded_modules
    ]

    registry_modules = {info["module"] for info in all_cog_info}
    for ext in loaded_modules:
        if ext not in registry_modules:
            short = ext.rsplit(".", 1)[-1]
            loaded_cog_infos.append({
                "module": ext,
                "name": short.replace("_", " ").title(),
                "description": "",
                "category": "",
                "requires_admin": False,
            })

    async with db_session() as s:
        rows = (await s.scalars(
            select(CogState).where(CogState.server_id.is_(None)).order_by(CogState.cog_name)
        )).all()
    state_by_name = {r.cog_name: r.enabled for r in rows}

    cogs = sorted(
        (
            {
                "name": info["name"],
                "module": info["module"],
                "enabled": state_by_name.get(info["name"].lower(), True),
                "loaded": True,
                "description": info.get("description", ""),
                "category": info.get("category", ""),
            }
            for info in loaded_cog_infos
        ),
        key=lambda c: c["name"],
    )

    async with db_session() as s:
        servers = (await s.scalars(select(Server).order_by(Server.name))).all()
        per_server_rows = (await s.scalars(select(ServerCogState))).all()
    per_server: dict[int, dict[str, bool]] = {}
    for r in per_server_rows:
        per_server.setdefault(r.server_id, {})[r.cog_name] = r.enabled
    cog_names = [c["name"] for c in cogs]
    return _render(
        request,
        "cogs/cogs.html",
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
                updated_at=_dt.now(tz=UTC),
            )
            s.add(row)
        else:
            row.enabled = not row.enabled
            row.updated_at = _dt.now(tz=UTC)
    try:
        from bot.runtime import invalidate_cog_state_cache
        invalidate_cog_state_cache(server_id=server_id, cog_name=cog_name)
    except Exception:
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
    except Exception:
        pass
    return RedirectResponse("/cogs", status_code=303)


@router.get("/marketplace", response_class=HTMLResponse)
async def marketplace_view(request: Request,
                           access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE)) -> HTMLResponse:
    user = await _require_user(access_token)
    if user.role != WebRole.ADMIN:
        return _render(request, "error.html", user=user, status=403,
                       title="Forbidden", detail="Admin only.")
    return _render(request, "cogs/marketplace.html", user=user)
