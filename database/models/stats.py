"""Statistics events + aggregates."""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, Enum, ForeignKey, Index, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base


class StatEventType(str, enum.Enum):
    MESSAGE = "message"
    COMMAND = "command"
    MODERATION = "moderation"
    JOIN = "join"
    LEAVE = "leave"


class StatEvent(Base):
    """Raw fire-and-forget event row. Aggregated periodically."""

    __tablename__ = "stat_events"
    __table_args__ = (
        Index("ix_stat_events_server_type_at", "server_id", "event_type", "occurred_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    server_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("servers.id", ondelete="CASCADE"), nullable=True
    )
    event_type: Mapped[StatEventType] = mapped_column(
        Enum(StatEventType, name="stat_event_type"), nullable=False
    )
    user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    name: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AggregatedStat(Base):
    """Daily rollups, queried by the dashboard."""

    __tablename__ = "aggregated_stats"
    __table_args__ = (
        Index(
            "uq_agg_stats_unique",
            "day",
            "server_id",
            "event_type",
            "name",
            unique=True,
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    day: Mapped[date] = mapped_column(Date, nullable=False)
    server_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    event_type: Mapped[StatEventType] = mapped_column(
        Enum(StatEventType, name="stat_event_type"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
