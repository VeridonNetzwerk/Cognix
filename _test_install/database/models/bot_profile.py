"""Bot cosmetic profile (display name, avatar, banner, activity)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base


class BotProfile(Base):
    """Singleton (id=1) row holding the editable bot profile."""

    __tablename__ = "bot_profile"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    display_name: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    about_me: Mapped[str] = mapped_column(Text, default="", nullable=False)
    avatar_data: Mapped[str] = mapped_column(Text, default="", nullable=False)  # data URL
    banner_data: Mapped[str] = mapped_column(Text, default="", nullable=False)  # data URL
    activity_type: Mapped[str] = mapped_column(String(16), default="playing", nullable=False)
    activity_text: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="online", nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
