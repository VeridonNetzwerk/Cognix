"""Music play history — every track that started playing.

Used by the dashboard "Latest" and "Most Played" tabs and by the bot for
suggestions. Stores resolved metadata at play time so the entry stays
useful even if the source URL goes 404.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base


class MusicPlayHistory(Base):
    __tablename__ = "music_play_history"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    server_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    url: Mapped[str] = mapped_column(String(1024), nullable=False, default="")
    thumbnail: Mapped[str] = mapped_column(String(1024), nullable=False, default="")
    duration: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    played_by: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    played_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
