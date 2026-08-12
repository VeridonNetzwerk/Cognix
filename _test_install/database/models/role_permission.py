"""Per-server Discord-role to command-permission mapping."""

from __future__ import annotations

from sqlalchemy import JSON, BigInteger, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.base import Base, TimestampMixin


class RolePermission(Base, TimestampMixin):
    __tablename__ = "role_permissions"
    __table_args__ = (
        UniqueConstraint("server_id", "discord_role_id", "command", name="uq_role_perm"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    server_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("servers.id", ondelete="CASCADE"), nullable=False
    )
    discord_role_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    command: Mapped[str] = mapped_column(String(64), nullable=False)
    allowed: Mapped[bool] = mapped_column(default=True, nullable=False)
    extras: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)

    server = relationship("Server", back_populates="role_permissions")
