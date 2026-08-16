"""add music_settings table

Revision ID: 0012_music_settings
Revises: 0011_user_dashboard_widgets
Create Date: 2026-08-16
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0012_music_settings"
down_revision = "0011_user_dashboard_widgets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    tables = inspector.get_table_names()
    if "music_settings" not in tables:
        op.create_table(
            "music_settings",
            sa.Column("server_id", sa.BigInteger(), primary_key=True),
            sa.Column("dj_role_id", sa.BigInteger(), nullable=True),
            sa.Column("music_channel_id", sa.BigInteger(), nullable=True),
            sa.Column("default_volume", sa.Integer(), server_default="100", nullable=False),
            sa.Column("auto_play", sa.Boolean(), server_default="0", nullable=False),
            sa.Column("eq_preset", sa.String(32), server_default="flat", nullable=False),
            sa.Column("vote_skip", sa.Boolean(), server_default="0", nullable=False),
            sa.Column("vote_skip_threshold", sa.Float(), server_default="0.5", nullable=False),
        )


def downgrade() -> None:
    op.drop_table("music_settings")
