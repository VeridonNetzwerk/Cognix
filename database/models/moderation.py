"""Moderation: actions + warnings."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, Index, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.base import Base, TimestampMixin


class ModerationActionType(str, enum.Enum):
    BAN = "ban"
    UNBAN = "unban"
    KICK = "kick"
    MUTE = "mute"
    UNMUTE = "unmute"
    WARN = "warn"
    PURGE = "purge"


class ModerationAction(Base, TimestampMixin):
    __tablename__ = "moderation_actions"
    __table_args__ = (
        Index("ix_moderation_actions_server_target", "server_id", "target_id"),
        Index("ix_moderation_actions_created_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    server_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("servers.id", ondelete="CASCADE"), nullable=False
    )

    action_type: Mapped[ModerationActionType] = mapped_column(
        Enum(ModerationActionType, name="moderation_action_type"), nullable=False
    )
    target_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("discord_users.id", ondelete="SET NULL"), nullable=True
    )
    moderator_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    reason: Mapped[str] = mapped_column(Text, default="", nullable=False)

    # For mutes & temp bans
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # For purge
    affected_count: Mapped[int] = mapped_column(default=0, nullable=False)
    channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    # Web user that triggered the action via dashboard (nullable = bot-side)
    web_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("web_users.id", ondelete="SET NULL"), nullable=True
    )

    server = relationship("Server", back_populates="moderation_actions")
    target = relationship("DiscordUser", back_populates="moderation_actions", foreign_keys=[target_id])


class Warning_(Base, TimestampMixin):
    """``Warning`` is shadowed by builtins; trailing underscore."""

    __tablename__ = "warnings"
    __table_args__ = (Index("ix_warnings_server_target", "server_id", "target_id"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    server_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("servers.id", ondelete="CASCADE"), nullable=False
    )
    target_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("discord_users.id", ondelete="CASCADE"), nullable=False
    )
    moderator_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    reason: Mapped[str] = mapped_column(Text, default="", nullable=False)
    severity: Mapped[int] = mapped_column(default=1, nullable=False)

    server = relationship("Server", back_populates="warnings")
    target = relationship("DiscordUser", back_populates="warnings")
