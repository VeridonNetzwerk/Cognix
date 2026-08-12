"""Server backups (roles/channels/permissions snapshots)."""

from __future__ import annotations

import uuid

from sqlalchemy import JSON, BigInteger, ForeignKey, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.base import Base, TimestampMixin


class Backup(Base, TimestampMixin):
    __tablename__ = "backups"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    server_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("servers.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_by: Mapped[int] = mapped_column(BigInteger, nullable=False)

    # Encrypted JSON payload (channels/roles/perms)
    payload_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    payload_size_bytes: Mapped[int] = mapped_column(default=0, nullable=False)
    schema_version: Mapped[int] = mapped_column(default=1, nullable=False)

    # Non-secret summary for listing
    summary: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)

    server = relationship("Server", back_populates="backups")
