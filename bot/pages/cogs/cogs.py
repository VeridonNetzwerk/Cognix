"""Cogs management routes — marketplace + global load/unload + per-server enable/disable."""

from __future__ import annotations

from datetime import UTC
from datetime import datetime as _dt

from pathlib import Path

from fastapi import Cookie, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from sqlalchemy import select

from bot.cogs.registry import (
    COG_CATEGORIES,
    COG_CATEGORY_ALL,
    get_all_cog_info,
    get_store_cog_info,
    get_cog_updates,
    load_cog,
    unload_cog,
    reload_cog,
    get_cog_requirements,
    get_cog_files,
)
from bot.runtime import get_bot
from bot.cogs import github_store
from bot.database.models.cogs.cog_state import CogState
from bot.database.models.server.server import Server
from bot.database.models.server.server_cog_state import ServerCogState
from bot.database.session import db_session
from web.deps import ACCESS_COOKIE
from bot.pages._shared import _get_loaded_cogs_set, _get_selected_server_id, _render, _require_user, router


@router.get("/cogs", response_class=HTMLResponse)
async def cogs_view(request: Request,
                    access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE)) -> HTMLResponse:
    user = await _require_user(access_token)

    # Pull the store catalog from GitHub (cached) so the marketplace is populated
    # even when cogs_store/ is not bundled locally.
    store_ok = await github_store.ensure_store_cache()
    from bot.cogs.registry import refresh_store_cache as _refresh_store_cache
    _refresh_store_cache()
    store_sync = github_store.get_sync_status()

    all_cog_infos = get_all_cog_info()
    loaded_set = _get_loaded_cogs_set()

    # Global enable/disable state from CogState (server_id=None)
    selected_server_id = _get_selected_server_id(request)
    async with db_session() as s:
        rows = (await s.scalars(
            select(CogState).where(CogState.server_id.is_(None)).order_by(CogState.cog_name)
        )).all()
    state_by_name = {r.cog_name: r.enabled for r in rows}

    # Per-server override for selected server
    server_state_by_name: dict[str, bool] = {}
    if selected_server_id:
        async with db_session() as s:
            sv_rows = (await s.scalars(
                select(ServerCogState).where(ServerCogState.server_id == selected_server_id)
            )).all()
        server_state_by_name = {r.cog_name: r.enabled for r in sv_rows}

    # Build installed cog lookup
    installed_map: dict[str, dict] = {}
    for info in all_cog_infos:
        cog_name_lower = info["name"].lower()
        if selected_server_id and cog_name_lower in server_state_by_name:
            enabled = server_state_by_name[cog_name_lower]
        else:
            enabled = state_by_name.get(cog_name_lower, True)
        installed_map[info["module"]] = {
            "name": info["name"],
            "module": info["module"],
            "description": info.get("description", ""),
            "category": info.get("category", ""),
            "requires_admin": info.get("requires_admin", False),
            "icon_url": info.get("icon_url"),
            "version": info.get("version", ""),
            "installed": True,
            "loaded": info["module"] in loaded_set,
            "enabled": enabled,
            "requirements": [],
            "extra_files": [],
            "verified": info.get("verified", False),
            "permissions": info.get("permissions", []),
        }

    # Build store cog list (available to install)
    store_cog_infos = get_store_cog_info()
    installed_modules = {c["module"] for c in all_cog_infos}
    store_map: dict[str, dict] = {}
    for info in store_cog_infos:
        store_map[info["module"]] = {
            "name": info["name"],
            "module": info["module"],
            "description": info.get("description", ""),
            "category": info.get("category", ""),
            "requires_admin": info.get("requires_admin", False),
            "icon_url": info.get("icon_url"),
            "version": info.get("version", ""),
            "installed": info["module"] in installed_modules,
            "loaded": False,
            "enabled": False,
            "requirements": get_cog_requirements(info["module"]),
            "extra_files": get_cog_files(info["module"]),
            "verified": info.get("verified", False),
            "permissions": info.get("permissions", []),
        }

    # Merge: all installed cogs + all store cogs (dedup by module)
    all_cogs = list(installed_map.values())
    for module, info in store_map.items():
        if module not in installed_map:
            all_cogs.append(info)

    # Sort by category then name
    all_cogs.sort(key=lambda c: (c["category"], c["name"]))

    # Per-server override data
    async with db_session() as s:
        servers = (await s.scalars(select(Server).order_by(Server.name))).all()
        per_server_rows = (await s.scalars(select(ServerCogState))).all()
    per_server: dict[int, dict[str, bool]] = {}
    for r in per_server_rows:
        per_server.setdefault(r.server_id, {})[r.cog_name] = r.enabled

    # Only show loaded cog names in per-server table
    loaded_cog_names = [c["name"] for c in all_cogs if c["loaded"]]

    # Check for updates
    cog_updates = get_cog_updates()

    return _render(
        request,
        "cogs/cogs.html",
        user=user,
        cogs=all_cogs,
        servers=servers,
        per_server=per_server,
        cog_names=loaded_cog_names,
        categories={k: v for k, v in COG_CATEGORIES.items() if k != "Core"},
        category_all=COG_CATEGORY_ALL,
        updates=cog_updates,
        store_available=store_ok,
        store_sync=store_sync,
        selected_server_id=_get_selected_server_id(request),
    )


@router.get("/cogs/icon/{cog_dir}/{filename}")
async def cog_icon(cog_dir: str, filename: str) -> Response:
    """Serve a cog icon from cogs/, cogs_store/, or the GitHub store cache."""
    base = Path(__file__).resolve().parent.parent.parent.parent
    roots = [base / "cogs", base / "cogs_store"]
    try:
        from bot.cogs.github_store import get_github_store_base

        roots.append(get_github_store_base() / "cogs_store")
    except Exception:  # noqa: BLE001
        pass
    for root in roots:
        candidate = root / cog_dir / filename
        if candidate.exists() and candidate.is_file():
            if candidate.suffix in (".png", ".svg", ".jpg", ".jpeg", ".webp", ".gif"):
                return FileResponse(str(candidate))
    return Response(status_code=404)


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
                enabled=True,
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


@router.post("/cogs/{cog_name}/load")
async def cogs_load(cog_name: str,
                    access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE)) -> Response:
    await _require_user(access_token)
    bot = get_bot()
    try:
        if bot is not None:
            await load_cog(bot, cog_name)
        else:
            from web.services.bot_ipc import get_ipc
            try:
                await get_ipc().call("cog.load", {"name": cog_name}, timeout=5.0)
            except Exception:  # noqa: BLE001
                pass
    except Exception:  # noqa: BLE001
        # Fallback for non-JS clients — never surface a raw 500.
        pass
    return RedirectResponse("/cogs", status_code=303)


@router.post("/cogs/{cog_name}/unload")
async def cogs_unload(cog_name: str,
                       access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE)) -> Response:
    await _require_user(access_token)
    bot = get_bot()
    try:
        if bot is not None:
            await unload_cog(bot, cog_name)
        else:
            from web.services.bot_ipc import get_ipc
            try:
                await get_ipc().call("cog.unload", {"name": cog_name}, timeout=5.0)
            except Exception:  # noqa: BLE001
                pass
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
    try:
        from bot.runtime import invalidate_cog_state_cache
        invalidate_cog_state_cache(cog_name=cog_name)
    except Exception:
        pass
    return RedirectResponse("/cogs", status_code=303)


@router.post("/cogs/{cog_name}/reload")
async def cogs_reload(cog_name: str,
                       access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE)) -> Response:
    await _require_user(access_token)
    bot = get_bot()
    try:
        if bot is not None:
            try:
                await reload_cog(bot, cog_name)
            except Exception:  # noqa: BLE001
                pass
        else:
            from web.services.bot_ipc import get_ipc
            try:
                await get_ipc().call("cog.reload", {"name": cog_name}, timeout=5.0)
            except Exception:  # noqa: BLE001
                pass
    except Exception:  # noqa: BLE001
        pass
    return RedirectResponse("/cogs", status_code=303)
