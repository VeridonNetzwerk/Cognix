"""Stream announcer models — per-server config and tracked stream sessions."""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from bot.database.base import Base, TimestampMixin


class StreamAnnouncerConfig(Base, TimestampMixin):
    """One row per server. Stores stream announcer settings."""

    __tablename__ = "stream_announcer_configs"

    server_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("servers.id", ondelete="CASCADE"), primary_key=True
    )

    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Channel where stream announcements are posted
    announce_channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    # Message template with placeholders: {user.mention}, {user.name}, {stream_url},
    # {stream_title}, {game}, {guild.name}
    announce_message: Mapped[str] = mapped_column(
        Text,
        default="🔴 **{user.name}** is now streaming!\n**{stream_title}**\n{stream_url}",
        nullable=False,
    )

    # Platforms to track (empty = all). Values: "twitch", "youtube", "custom"
    tracked_platforms: Mapped[list] = mapped_column(JSON, default=list, nullable=False)

    # Roles that are allowed to be tracked (empty = everyone)
    tracked_roles: Mapped[list] = mapped_column(JSON, default=list, nullable=False)

    # Roles to ignore (bots, etc.)
    ignored_roles: Mapped[list] = mapped_column(JSON, default=list, nullable=False)

    # Whether to auto-add a "Streaming" role while the user is live
    streaming_role_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    # Whether to delete the announcement when the stream ends
    delete_on_end: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Whether to ping a role when announcing
    ping_role_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    # Cooldown between re-announcements for the same user (minutes)
    cooldown_minutes: Mapped[int] = mapped_column(Integer, default=60, nullable=False)


class StreamSession(Base, TimestampMixin):
    """Tracks an active or past stream session for a user."""

    __tablename__ = "stream_sessions"
    __table_args__ = (
        UniqueConstraint(
            "server_id", "user_id", "platform", "started_at",
            name="uq_stream_sessions_server_user_platform_start",
        ),
        Index("ix_stream_sessions_server_active", "server_id", "is_active"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    server_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("servers.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)

    # Platform: "twitch", "youtube", "custom"
    platform: Mapped[str] = mapped_column(String(32), default="twitch", nullable=False)

    # Stream details captured at announcement time
    stream_url: Mapped[str] = mapped_column(Text, default="", nullable=False)
    stream_title: Mapped[str] = mapped_column(Text, default="", nullable=False)
    game: Mapped[str] = mapped_column(String(256), default="", nullable=False)

    # The Discord message ID of the announcement (for deletion on end)
    announce_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    started_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    ended_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
