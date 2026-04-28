"""Discord activity log: per-server event stream (messages, mod actions, voice, …)."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import JSON, BigInteger, DateTime, Enum, Index, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base


class DiscordEventType(str, enum.Enum):
    MESSAGE_SENT = "message_sent"
    MESSAGE_EDITED = "message_edited"
    MESSAGE_DELETED = "message_deleted"
    MEMBER_JOIN = "member_join"
    MEMBER_LEAVE = "member_leave"
    MEMBER_BAN = "member_ban"
    MEMBER_UNBAN = "member_unban"
    MEMBER_ROLE_ADDED = "member_role_added"
    MEMBER_ROLE_REMOVED = "member_role_removed"
    CHANNEL_CREATED = "channel_created"
    CHANNEL_DELETED = "channel_deleted"
    VOICE_JOIN = "voice_join"
    VOICE_LEAVE = "voice_leave"
    VOICE_MOVE = "voice_move"
    SLASH_COMMAND = "slash_command"
    TICKET_OPENED = "ticket_opened"
    TICKET_CLOSED = "ticket_closed"
    OTHER = "other"


class DiscordEvent(Base):
    """Persistent audit row for a single Discord-side event."""

    __tablename__ = "discord_events"
    __table_args__ = (
        Index("ix_discord_events_server_created", "server_id", "created_at"),
        Index("ix_discord_events_type_created", "event_type", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )

    event_type: Mapped[DiscordEventType] = mapped_column(
        Enum(DiscordEventType, name="discord_event_type"), nullable=False
    )
    server_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    target_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    summary: Mapped[str] = mapped_column(String(512), default="", nullable=False)
    content: Mapped[str] = mapped_column(Text, default="", nullable=False)
    extras: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
