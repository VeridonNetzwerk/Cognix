"""Reaction role message model."""

from __future__ import annotations

import uuid

from sqlalchemy import JSON, BigInteger, ForeignKey, Index, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bot.database.base import Base, TimestampMixin


class ReactionRoleMessage(Base, TimestampMixin):
    """A message that grants roles when users react."""

    __tablename__ = "reaction_role_messages"
    __table_args__ = (
        Index("ix_reaction_roles_guild_message", "guild_id", "message_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    guild_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("servers.id", ondelete="CASCADE"), nullable=False
    )
    channel_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    message_id: Mapped[int] = mapped_column(BigInteger, nullable=False)

    # JSON: [{"emoji": "👍", "role_id": 123, "mode": "toggle"}]
    # mode: "toggle" (add on react, remove on unreact) or "sticky" (add only)
    mappings: Mapped[list[dict]] = mapped_column(
        JSON, nullable=False, default=list
    )

    title: Mapped[str] = mapped_column(String(256), default="", nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)

    server = relationship("Server", backref="reaction_role_messages")
