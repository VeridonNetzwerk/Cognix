"""Singleton system configuration row."""

from __future__ import annotations

from sqlalchemy import Boolean, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base, TimestampMixin


class SystemConfig(Base, TimestampMixin):
    """One-row table holding global system flags + encrypted bot token."""

    __tablename__ = "system_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)

    configured: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Encrypted (AES-GCM) values
    bot_token_encrypted: Mapped[str] = mapped_column(Text, default="", nullable=False)
    google_oauth_client_id_encrypted: Mapped[str] = mapped_column(Text, default="", nullable=False)
    google_oauth_client_secret_encrypted: Mapped[str] = mapped_column(
        Text, default="", nullable=False
    )

    # Plaintext bot metadata
    bot_application_id: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    bot_status_text: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    bot_status_type: Mapped[str] = mapped_column(String(16), default="playing", nullable=False)
    bot_description: Mapped[str] = mapped_column(Text, default="", nullable=False)

    # Feature toggles
    google_oauth_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    music_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    registration_open: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
