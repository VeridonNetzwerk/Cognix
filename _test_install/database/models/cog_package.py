"""Cognitive marketplace package registry — stores information about installed and available cogs."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base, TimestampMixin


class CogPackage(Base, TimestampMixin):
    """Represents a cog package from the marketplace."""

    __tablename__ = "cog_packages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Package identity
    name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)

    # Source
    github_repo: Mapped[str] = mapped_column(String(512), default="", nullable=False)  # e.g. "https://github.com/user/cognix-cog-moderation"
    branch: Mapped[str] = mapped_column(String(64), default="main", nullable=False)

    # Version tracking
    version: Mapped[str | None] = mapped_column(String(32), default=None, nullable=True)
    installed_version: Mapped[str | None] = mapped_column(String(32), default=None, nullable=True)

    # Metadata
    dependencies: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    category: Mapped[str] = mapped_column(String(64), default="General", nullable=False)
    requires_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    author: Mapped[str | None] = mapped_column(String(128), default=None, nullable=True)

    # Installation state
    installed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    install_dir: Mapped[str | None] = mapped_column(String(512), default=None, nullable=True)  # Path where the cog was cloned/installed
    module_name: Mapped[str | None] = mapped_column(String(256), default=None, nullable=True)  # e.g. "bot.cogs.ext_moderation"

    # Tracking
    last_installed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None, nullable=True)
    uninstall_requested: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
