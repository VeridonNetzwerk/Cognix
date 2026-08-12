"""Discord servers (guilds)."""

from __future__ import annotations

from sqlalchemy import BigInteger, Boolean, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.base import Base, SoftDeleteMixin, TimestampMixin


class Server(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "servers"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    icon_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    owner_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    member_count: Mapped[int] = mapped_column(default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    config = relationship(
        "ServerConfig", back_populates="server", uselist=False, cascade="all, delete-orphan"
    )
    moderation_actions = relationship(
        "ModerationAction", back_populates="server", cascade="all, delete-orphan"
    )
    warnings = relationship("Warning_", back_populates="server", cascade="all, delete-orphan")
    tickets = relationship("Ticket", back_populates="server", cascade="all, delete-orphan")
    backups = relationship("Backup", back_populates="server", cascade="all, delete-orphan")
    cog_states = relationship("CogState", back_populates="server", cascade="all, delete-orphan")
    role_permissions = relationship(
        "RolePermission", back_populates="server", cascade="all, delete-orphan"
    )
