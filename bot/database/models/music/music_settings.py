"""Per-server music settings (DJ role, music channel, auto-play, EQ, vote skip)."""

from __future__ import annotations

from sqlalchemy import BigInteger, Boolean, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from bot.database.base import Base


class MusicSettings(Base):
    __tablename__ = "music_settings"

    server_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    dj_role_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    music_channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    default_volume: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    auto_play: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    eq_preset: Mapped[str] = mapped_column(String(32), nullable=False, default="flat")
    vote_skip: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    vote_skip_threshold: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
