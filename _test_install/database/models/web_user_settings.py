"""Per-user UI settings (theme, font size) and granular module permissions."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base


class WebUserSettings(Base):
    __tablename__ = "web_user_settings"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("web_users.id", ondelete="CASCADE"), primary_key=True
    )
    theme: Mapped[str] = mapped_column(String(32), default="dark", nullable=False)
    accent_color: Mapped[str] = mapped_column(String(16), default="#60A5FA", nullable=False)
    font_size: Mapped[str] = mapped_column(String(16), default="medium", nullable=False)
    extras: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class PermissionLevel(str, enum.Enum):
    NONE = "none"
    READ = "read"
    WRITE = "write"


# Canonical list of dashboard modules subject to permission gating.
MODULES: list[str] = [
    "servers",
    "cogs",
    "embeds",
    "music",
    "tickets",
    "backups",
    "log",
    "web_users",
    "bot_profile",
    "members",
    "giveaways",
    "welcome",
    "invites",
]


class WebUserModulePermission(Base):
    __tablename__ = "web_user_module_permissions"
    __table_args__ = (UniqueConstraint("user_id", "module", name="uq_web_user_module"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("web_users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    module: Mapped[str] = mapped_column(String(64), nullable=False)
    level: Mapped[str] = mapped_column(String(16), default="none", nullable=False)
