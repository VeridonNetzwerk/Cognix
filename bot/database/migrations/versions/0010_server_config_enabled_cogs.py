"""add enabled_cogs column to server_configs

Revision ID: 0010_server_config_enabled_cogs
Revises: 0009_cog_packages
Create Date: 2026-08-12
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0010_server_config_enabled_cogs"
down_revision = "0009_cog_packages"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Only add column if it doesn't exist (idempotent)
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = [col["name"] for col in inspector.get_columns("server_configs")]
    if "enabled_cogs" not in columns:
        op.add_column(
            "server_configs",
            sa.Column("enabled_cogs", sa.JSON(), server_default="[]", nullable=False),
        )


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = [col["name"] for col in inspector.get_columns("server_configs")]
    if "enabled_cogs" in columns:
        op.drop_column("server_configs", "enabled_cogs")
