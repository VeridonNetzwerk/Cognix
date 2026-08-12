"""Initial schema.

Revision ID: 0001_initial
Revises:
Create Date: 2026-04-25

This migration uses ``Base.metadata.create_all`` for portability across
SQLite/PostgreSQL/MySQL. Subsequent migrations should use explicit ops.
"""
from __future__ import annotations

from alembic import op

from database.base import Base
from database import models  # noqa: F401

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)
    # Ensure the singleton system_config row exists.
    op.execute(
        "INSERT INTO system_config (id, configured) VALUES (1, FALSE) "
        "ON CONFLICT DO NOTHING"
        if bind.dialect.name == "postgresql"
        else "INSERT OR IGNORE INTO system_config (id, configured) VALUES (1, 0)"
        if bind.dialect.name == "sqlite"
        else "INSERT IGNORE INTO system_config (id, configured) VALUES (1, FALSE)"
    )


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
