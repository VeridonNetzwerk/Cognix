"""Cog enable/disable state per server (and global)."""

from __future__ import annotations

from sqlalchemy import BigInteger, Boolean, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.base import Base, TimestampMixin


class CogState(Base, TimestampMixin):
    __tablename__ = "cog_states"
    __table_args__ = (UniqueConstraint("server_id", "cog_name", name="uq_cog_states_server_cog"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    # NULL server_id = global default
    server_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("servers.id", ondelete="CASCADE"), nullable=True
    )
    cog_name: Mapped[str] = mapped_column(String(64), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    server = relationship("Server", back_populates="cog_states")
