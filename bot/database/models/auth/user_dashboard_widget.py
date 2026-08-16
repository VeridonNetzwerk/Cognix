"""Per-user dashboard widget layout (like a smartphone home screen)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from bot.database.base import Base


class UserDashboardWidget(Base):
    __tablename__ = "user_dashboard_widgets"
    __table_args__ = (UniqueConstraint("user_id", "widget_id", name="uq_user_widget"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("web_users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    widget_id: Mapped[str] = mapped_column(String(64), nullable=False)
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    visible: Mapped[bool] = mapped_column(default=True, nullable=False)
    size_w: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    size_h: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
