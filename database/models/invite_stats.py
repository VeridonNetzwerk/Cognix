"""Invite tracker — per-server / per-inviter aggregate stats."""

from __future__ import annotations

from sqlalchemy import BigInteger, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base, TimestampMixin


class InviteStats(Base, TimestampMixin):
    __tablename__ = "invite_stats"
    __table_args__ = (UniqueConstraint("server_id", "inviter_id", name="uq_invite_stats"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    server_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    inviter_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    total_uses: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    active_uses: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    left_uses: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    fake_uses: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
