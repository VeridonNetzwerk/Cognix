"""Multi-type / multi-panel ticket configuration."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import BigInteger, JSON, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base, TimestampMixin


class TicketType(Base, TimestampMixin):
    """A ticket category (e.g. Support, Bewerbung, Partnership)."""

    __tablename__ = "ticket_types"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    server_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str] = mapped_column(String(256), default="", nullable=False)
    emoji: Mapped[str] = mapped_column(String(16), default="", nullable=False)
    category_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    ping_role_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    welcome_embed: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)


class TicketPanel(Base, TimestampMixin):
    """A panel (message) that exposes one or more ticket types as buttons."""

    __tablename__ = "ticket_panels"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    server_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    embed: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    # buttons is list of {label, style, emoji, ticket_type_id (uuid str), url, custom_id}
    buttons: Mapped[list[Any]] = mapped_column(JSON, default=list, nullable=False)
