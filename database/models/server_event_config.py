"""Server-event message configs (join/leave/boost)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import BigInteger, Boolean, ForeignKey, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base, TimestampMixin


class ServerEventConfig(Base, TimestampMixin):
    """One row per server. Stores join/leave/boost message configs as JSON."""

    __tablename__ = "server_event_configs"

    server_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("servers.id", ondelete="CASCADE"), primary_key=True
    )

    join_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    join_channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    join_embed: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    leave_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    leave_channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    leave_embed: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    boost_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    boost_channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    boost_embed: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
