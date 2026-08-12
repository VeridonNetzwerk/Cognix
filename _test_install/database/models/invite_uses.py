"""Per-join invite use record."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base, TimestampMixin


class InviteUse(Base, TimestampMixin):
    __tablename__ = "invite_uses"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    server_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    invitee_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    inviter_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    left_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
