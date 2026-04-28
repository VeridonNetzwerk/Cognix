"""Per-server configuration."""

from __future__ import annotations

from sqlalchemy import JSON, BigInteger, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.base import Base, TimestampMixin


class ServerConfig(Base, TimestampMixin):
    __tablename__ = "server_configs"

    server_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("servers.id", ondelete="CASCADE"), primary_key=True
    )
    prefix: Mapped[str] = mapped_column(String(8), default="!", nullable=False)
    locale: Mapped[str] = mapped_column(String(8), default="en", nullable=False)

    mod_log_channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    mute_role_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    welcome_channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    ticket_category_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    ticket_support_role_ids: Mapped[list[int]] = mapped_column(JSON, default=list, nullable=False)
    ticket_auto_close_hours: Mapped[int] = mapped_column(default=72, nullable=False)

    music_dj_role_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    extras: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)

    server = relationship("Server", back_populates="config")
