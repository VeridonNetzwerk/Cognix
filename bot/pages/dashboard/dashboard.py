"""Dashboard and server-selection routes."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import Cookie, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import desc, select

from bot.cogs.registry import get_available_widgets
from bot.dashboard.widgets import CORE_WIDGETS, compute_metrics, default_widget_size, load_widget_data
from bot.database.models.auth.audit_log import AuditLog
from bot.database.models.auth.user_dashboard_widget import UserDashboardWidget
from bot.database.models.server.server import Server
from bot.database.models.server.server_config import ServerConfig
from bot.database.session import db_session
from web.deps import ACCESS_COOKIE
from bot.pages._shared import (
    _current_user,
    _render,
    _require_user,
    _system_configured,
    router,
)

_GRID_COLS = 4
_GRID_ROWS = 3
_DEFAULT_WIDGET_IDS = ["metrics_overview", "bot_status"]


def _assign_grid_positions(
    active_widgets: list[dict],
    user_layout: dict[str, UserDashboardWidget],
) -> None:
    """Assign grid positions to widgets. Explicitly placed widgets keep their spot;
    unplaced widgets get greedy left-to-right, top-to-bottom placement."""
    occupied: set[tuple[int, int]] = set()

    # Register explicitly placed widgets first
    for w in active_widgets:
        uw = user_layout.get(w["id"])
        if uw and uw.grid_col > 0 and uw.grid_row > 0:
            w["grid_col"] = uw.grid_col
            w["grid_row"] = uw.grid_row
            sw, sh = w.get("size_w", 1), w.get("size_h", 1)
            for dc in range(sw):
                for dr in range(sh):
                    c, r = uw.grid_col + dc, uw.grid_row + dr
                    if 1 <= c <= _GRID_COLS and 1 <= r <= _GRID_ROWS:
                        occupied.add((c, r))
        else:
            w["grid_col"] = 0
            w["grid_row"] = 0

    # Auto-assign positions for unplaced widgets
    for w in active_widgets:
        if w["grid_col"] > 0:
            continue
        sw, sh = w.get("size_w", 1), w.get("size_h", 1)
        placed = False
        for row in range(1, _GRID_ROWS + 1):
            for col in range(1, _GRID_COLS + 1):
                fits = all(
                    col + dc <= _GRID_COLS and row + dr <= _GRID_ROWS and (col + dc, row + dr) not in occupied
                    for dc in range(sw) for dr in range(sh)
                )
                if fits:
                    w["grid_col"] = col
                    w["grid_row"] = row
                    for dc in range(sw):
                        for dr in range(sh):
                            occupied.add((col + dc, row + dr))
                    placed = True
                    break
            if placed:
                break
        if not placed:
            w["grid_col"] = 1
            w["grid_row"] = 1


def _build_active_widget_list(
    active_widget_ids: list[str],
    available_widgets: list[dict],
    user_layout: dict[str, UserDashboardWidget],
) -> list[dict]:
    """Build ordered widget list with user size preferences applied."""
    widget_by_id = {w["id"]: w for w in available_widgets}
    result: list[dict] = []
    for wid in active_widget_ids:
        w_info = widget_by_id.get(wid)
        if w_info is None:
            continue
        w_copy = dict(w_info)
        uw = user_layout.get(wid)
        if uw and (uw.size_w or 0) > 0 and (uw.size_h or 0) > 0:
            w_copy["size_w"] = uw.size_w
            w_copy["size_h"] = uw.size_h
        else:
            dw, dh = default_widget_size(w_info.get("size", "small"))
            w_copy["size_w"] = dw
            w_copy["size_h"] = dh
        result.append(w_copy)
    return result


def _filter_active_widget_ids(
    user_widgets: list[UserDashboardWidget],
    available_widgets: list[dict],
) -> list[str]:
    """Return IDs of user widgets that are visible and still available."""
    available_ids = {aw["id"] for aw in available_widgets}
    return [w.widget_id for w in user_widgets if w.visible and w.widget_id in available_ids]


@router.get("/", response_class=HTMLResponse)
async def index(request: Request,
                access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE)) -> HTMLResponse:
    if not await _system_configured():
        return RedirectResponse("/setup", status_code=303)
    user = await _current_user(access_token)
    if user is None:
        return RedirectResponse("/login", status_code=303)

    async with db_session() as s:
        metrics = await compute_metrics(s, user)
        recent = (await s.scalars(
            select(AuditLog).order_by(desc(AuditLog.created_at)).limit(8)
        )).all()
        from web.security.permissions import has_permission as _hp
        can_servers_write = await _hp(s, user, "servers", level="write")

    # --- Widget system ---
    available_widgets = [*CORE_WIDGETS, *get_available_widgets()]

    # Load user's widget layout from DB
    async with db_session() as s:
        user_widgets = (await s.scalars(
            select(UserDashboardWidget)
            .where(UserDashboardWidget.user_id == user.id)
            .order_by(UserDashboardWidget.position)
        )).all()
    user_layout = {w.widget_id: w for w in user_widgets}
    active_widget_ids = _filter_active_widget_ids(user_widgets, available_widgets)

    # If no layout saved yet, create DB entries for default widgets
    if not active_widget_ids:
        default_ids = list(_DEFAULT_WIDGET_IDS)
        available_widget_ids = {w["id"] for w in available_widgets}
        if "recent_audit" in available_widget_ids:
            default_ids.append("recent_audit")
        async with db_session() as s:
            for i, wid in enumerate(default_ids):
                size_str = next((aw.get("size", "medium") for aw in available_widgets if aw["id"] == wid), "medium")
                dw, dh = default_widget_size(size_str)
                s.add(UserDashboardWidget(
                    user_id=user.id,
                    widget_id=wid,
                    position=i,
                    visible=True,
                    size_w=dw,
                    size_h=dh,
                    grid_col=0,
                    grid_row=0,
                    updated_at=datetime.now(tz=UTC),
                ))
            await s.commit()
            user_widgets = (await s.scalars(
                select(UserDashboardWidget)
                .where(UserDashboardWidget.user_id == user.id)
                .order_by(UserDashboardWidget.position)
            )).all()
        user_layout = {w.widget_id: w for w in user_widgets}
        active_widget_ids = _filter_active_widget_ids(user_widgets, available_widgets)

    active_widgets = _build_active_widget_list(active_widget_ids, available_widgets, user_layout)
    _assign_grid_positions(active_widgets, user_layout)

    async with db_session() as s:
        widget_data = await load_widget_data(s, active_widget_ids, recent)

    available_to_add = [w for w in available_widgets if w["id"] not in active_widget_ids]

    return _render(
        request,
        "dashboard/dashboard.html",
        user=user,
        metrics=metrics,
        recent_audit=recent,
        can_servers_write=can_servers_write,
        active_widgets=active_widgets,
        available_widgets=available_widgets,
        available_to_add=available_to_add,
        widget_data=widget_data,
    )


@router.get("/select-server/{server_id}")
async def select_server(server_id: str, request: Request,
                        access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE)) -> RedirectResponse:
    await _require_user(access_token)
    response = RedirectResponse(request.headers.get("referer", "/"), status_code=303)
    try:
        sid = int(server_id)
    except ValueError:
        sid = 0
    if sid == 0:
        response.delete_cookie("selected_server_id", path="/")
    else:
        response.set_cookie("selected_server_id", str(sid), path="/", max_age=60*60*24*365, httponly=True, samesite="lax")
    return response


@router.get("/servers", response_class=HTMLResponse)
async def servers_view(request: Request,
                       access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE)) -> HTMLResponse:
    user = await _require_user(access_token)
    async with db_session() as s:
        rows = (await s.scalars(select(Server).order_by(Server.name))).all()
    return _render(request, "dashboard/servers.html", user=user, servers=rows)


@router.get("/servers/{server_id}", response_class=HTMLResponse)
async def server_detail(request: Request, server_id: int,
                        access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE)) -> HTMLResponse:
    user = await _require_user(access_token)
    async with db_session() as s:
        srv = await s.get(Server, server_id)
        cfg = await s.get(ServerConfig, server_id)
    if srv is None:
        return _render(request, "error.html", user=user, status=404,
                       title="Server not found", detail="No such server.")
    return _render(
        request,
        "dashboard/server_detail.html",
        user=user,
        server=srv,
        config=cfg or {},
    )
