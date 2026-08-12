"""Customizable embed templates (info, ticket panel, music panel, etc.)."""

from __future__ import annotations

from sqlalchemy import JSON, BigInteger, Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base, TimestampMixin


class EmbedTemplate(Base, TimestampMixin):
    """A reusable embed definition.

    ``key`` identifies the use site (e.g. ``info``, ``ticket_panel``,
    ``music_now_playing``). ``server_id`` is NULL for global templates;
    a per-server row overrides the global one when present.
    """

    __tablename__ = "embed_templates"
    __table_args__ = (UniqueConstraint("key", "server_id", name="uq_embed_templates_key_server"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    server_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("servers.id", ondelete="CASCADE"), nullable=True, index=True
    )
    key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    title: Mapped[str] = mapped_column(String(256), default="", nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    color: Mapped[int] = mapped_column(Integer, default=0x60A5FA, nullable=False)
    footer_text: Mapped[str] = mapped_column(String(2048), default="", nullable=False)
    footer_icon_url: Mapped[str] = mapped_column(String(512), default="", nullable=False)
    thumbnail_url: Mapped[str] = mapped_column(String(512), default="", nullable=False)
    image_url: Mapped[str] = mapped_column(String(512), default="", nullable=False)
    author_name: Mapped[str] = mapped_column(String(256), default="", nullable=False)
    author_icon_url: Mapped[str] = mapped_column(String(512), default="", nullable=False)
    author_url: Mapped[str] = mapped_column(String(512), default="", nullable=False)

    # Fields stored as list of {name, value, inline} dicts.
    fields: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    # Free-form extras (button labels, role mentions, etc.)
    extras: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
