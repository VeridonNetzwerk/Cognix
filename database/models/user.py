"""Discord users (global, cross-server)."""

from __future__ import annotations

from sqlalchemy import BigInteger, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.base import Base, TimestampMixin


class DiscordUser(Base, TimestampMixin):
    """A Discord user observed by the bot."""

    __tablename__ = "discord_users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    username: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    global_name: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    avatar_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_bot: Mapped[bool] = mapped_column(default=False, nullable=False)

    moderation_actions = relationship(
        "ModerationAction",
        back_populates="target",
        foreign_keys="ModerationAction.target_id",
    )
    warnings = relationship("Warning_", back_populates="target")
