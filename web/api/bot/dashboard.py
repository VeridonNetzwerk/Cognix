"""Dashboard widget layout API — add, remove, reorder widgets per user."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select

from bot.database.models.auth.user_dashboard_widget import UserDashboardWidget
from web.deps import SessionDep, get_current_user

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


class WidgetIdRequest(BaseModel):
    widget_id: str


class ReorderRequest(BaseModel):
    source_id: str
    target_id: str


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


@router.post("/widgets/reorder")
async def reorder_widget(
    req: ReorderRequest,
    session: SessionDep,
    user=Depends(get_current_user),
) -> dict:
    """Reorder widgets: swap source and target positions."""
    source = await session.scalar(
        select(UserDashboardWidget).where(
            UserDashboardWidget.user_id == user.id,
            UserDashboardWidget.widget_id == req.source_id,
        )
    )
    target = await session.scalar(
        select(UserDashboardWidget).where(
            UserDashboardWidget.user_id == user.id,
            UserDashboardWidget.widget_id == req.target_id,
        )
    )
    if source is not None and target is not None:
        source.position, target.position = target.position, source.position
        source.updated_at = datetime.now(tz=UTC)
        target.updated_at = datetime.now(tz=UTC)
    return {"ok": True}
