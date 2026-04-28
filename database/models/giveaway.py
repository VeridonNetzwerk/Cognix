"""Giveaway model."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, DateTime, Enum, JSON, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base, TimestampMixin


class GiveawayStatus(str, enum.Enum):
    ACTIVE = "active"
    ENDED = "ended"
    CANCELLED = "cancelled"


class Giveaway(Base, TimestampMixin):
    __tablename__ = "giveaways"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    server_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    channel_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    message_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True, unique=True)
    prize: Mapped[str] = mapped_column(String(256), nullable=False)
    winner_count: Mapped[int] = mapped_column(default=1, nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    ended: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    status: Mapped[GiveawayStatus] = mapped_column(
        Enum(GiveawayStatus, name="giveaway_status"), default=GiveawayStatus.ACTIVE, nullable=False
    )
    winners: Mapped[list[Any]] = mapped_column(JSON, default=list, nullable=False)
    required_role_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    host_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
