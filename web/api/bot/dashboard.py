"""Dashboard widget layout API — add, remove, reorder widgets per user."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import desc, select

from bot.dashboard.widgets import (
    CORE_WIDGETS,
    compute_metrics,
    default_widget_size,
    load_widget_data,
)
from bot.cogs.registry import get_available_widgets
from bot.database.models.auth.audit_log import AuditLog
from bot.database.models.auth.user_dashboard_widget import UserDashboardWidget
from bot.pages._shared import templates as jinja_templates
from web.deps import SessionDep, get_current_user
from web.security.permissions import has_permission

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


class WidgetIdRequest(BaseModel):
    widget_id: str


class MoveRequest(BaseModel):
    widget_id: str
    grid_col: int
    grid_row: int


class ResizeRequest(BaseModel):
    widget_id: str
    size_w: int
    size_h: int


@router.post("/widgets/add")
async def add_widget(
    req: WidgetIdRequest,
    session: SessionDep,
    user=Depends(get_current_user),
) -> dict:
    """Add a widget to the user's dashboard."""
    existing = await session.scalar(
        select(UserDashboardWidget).where(
            UserDashboardWidget.user_id == user.id,
            UserDashboardWidget.widget_id == req.widget_id,
        )
    )
    if existing is not None:
        existing.visible = True
        existing.updated_at = datetime.now(tz=UTC)
        return {"ok": True}

    # Get max position
    existing_widgets = (await session.scalars(
        select(UserDashboardWidget)
        .where(UserDashboardWidget.user_id == user.id)
        .order_by(UserDashboardWidget.position)
    )).all()
    max_pos = max((w.position for w in existing_widgets), default=-1)

    # Look up widget definition to get default size
    from bot.cogs.registry import get_available_widgets as _gaw
    from bot.dashboard.widgets import CORE_WIDGETS as _cw
    all_defs = list(_cw) + _gaw()
    widget_def = next((w for w in all_defs if w["id"] == req.widget_id), None)
    size_str = widget_def.get("size", "small") if widget_def else "small"
    dw, dh = default_widget_size(size_str)

    session.add(UserDashboardWidget(
        user_id=user.id,
        widget_id=req.widget_id,
        position=max_pos + 1,
        visible=True,
        size_w=dw,
        size_h=dh,
        grid_col=0,
        grid_row=0,
        updated_at=datetime.now(tz=UTC),
    ))
    return {"ok": True}


@router.post("/widgets/remove")
async def remove_widget(
    req: WidgetIdRequest,
    session: SessionDep,
    user=Depends(get_current_user),
) -> dict:
    """Remove a widget from the user's dashboard (hide it)."""
    widget = await session.scalar(
        select(UserDashboardWidget).where(
            UserDashboardWidget.user_id == user.id,
            UserDashboardWidget.widget_id == req.widget_id,
        )
    )
    if widget is not None:
        widget.visible = False
        widget.updated_at = datetime.now(tz=UTC)
    return {"ok": True}


@router.post("/widgets/move")
async def move_widget(
    req: MoveRequest,
    session: SessionDep,
    user=Depends(get_current_user),
) -> dict:
    """Move a widget to a specific grid position."""
    col = max(1, min(4, req.grid_col))
    row = max(1, min(3, req.grid_row))
    widget = await session.scalar(
        select(UserDashboardWidget).where(
            UserDashboardWidget.user_id == user.id,
            UserDashboardWidget.widget_id == req.widget_id,
        )
    )
    if widget is not None:
        widget.grid_col = col
        widget.grid_row = row
        widget.updated_at = datetime.now(tz=UTC)
    else:
        all_widgets = (await session.scalars(
            select(UserDashboardWidget)
            .where(UserDashboardWidget.user_id == user.id)
            .order_by(UserDashboardWidget.position)
        )).all()
        max_pos = max((w.position for w in all_widgets), default=-1)
        session.add(UserDashboardWidget(
            user_id=user.id,
            widget_id=req.widget_id,
            position=max_pos + 1,
            visible=True,
            grid_col=col,
            grid_row=row,
            updated_at=datetime.now(tz=UTC),
        ))
    return {"ok": True}


@router.get("/widgets/refresh")
async def refresh_widgets(
    session: SessionDep,
    user=Depends(get_current_user),
) -> dict:
    """Return freshly rendered HTML for all active widgets."""
    user_widgets = (await session.scalars(
        select(UserDashboardWidget)
        .where(UserDashboardWidget.user_id == user.id, UserDashboardWidget.visible.is_(True))
        .order_by(UserDashboardWidget.position)
    )).all()

    available_widgets = list(CORE_WIDGETS) + get_available_widgets()
    widget_by_id = {w["id"]: w for w in available_widgets}
    active_widget_ids = [
        w.widget_id for w in user_widgets
        if w.visible and w.widget_id in widget_by_id
    ]

    if not active_widget_ids:
        return {"widgets": {}}

    metrics = await compute_metrics(session, user)
    recent = (await session.scalars(
        select(AuditLog).order_by(desc(AuditLog.created_at)).limit(8)
    )).all()
    can_servers_write = await has_permission(session, user, "servers", level="write")
    widget_data = await load_widget_data(session, active_widget_ids, recent)

    result = {}
    for wid in active_widget_ids:
        w_info = widget_by_id.get(wid)
        if w_info is None:
            continue
        tmpl = jinja_templates.env.get_template(w_info["template"])
        html = tmpl.render(
            metrics=metrics,
            widget_data=widget_data.get(wid, {}),
            can_servers_write=can_servers_write,
            recent_audit=recent,
        )
        result[wid] = html

    return {"widgets": result}


@router.post("/widgets/resize")
async def resize_widget(
    req: ResizeRequest,
    session: SessionDep,
    user=Depends(get_current_user),
) -> dict:
    """Resize a widget on the user's dashboard."""
    # Clamp to reasonable bounds
    w = max(1, min(4, req.size_w))
    h = max(1, min(3, req.size_h))
    widget = await session.scalar(
        select(UserDashboardWidget).where(
            UserDashboardWidget.user_id == user.id,
            UserDashboardWidget.widget_id == req.widget_id,
        )
    )
    if widget is not None:
        widget.size_w = w
        widget.size_h = h
        widget.updated_at = datetime.now(tz=UTC)
    else:
        all_widgets = (await session.scalars(
            select(UserDashboardWidget)
            .where(UserDashboardWidget.user_id == user.id)
            .order_by(UserDashboardWidget.position)
        )).all()
        max_pos = max((ww.position for ww in all_widgets), default=-1)
        session.add(UserDashboardWidget(
            user_id=user.id,
            widget_id=req.widget_id,
            position=max_pos + 1,
            visible=True,
            size_w=w,
            size_h=h,
            grid_col=0,
            grid_row=0,
            updated_at=datetime.now(tz=UTC),
        ))
    return {"ok": True}
