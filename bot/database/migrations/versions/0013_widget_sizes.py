"""add size_w/size_h to user_dashboard_widgets

Revision ID: 0013_widget_sizes
Revises: 0012_music_settings
Create Date: 2026-08-16
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0013_widget_sizes"
down_revision = "0012_music_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = [c["name"] for c in inspector.get_columns("user_dashboard_widgets")]
    if "size_w" not in columns:
        op.add_column("user_dashboard_widgets",
                      sa.Column("size_w", sa.Integer(), server_default="1", nullable=False))
    if "size_h" not in columns:
        op.add_column("user_dashboard_widgets",
                      sa.Column("size_h", sa.Integer(), server_default="1", nullable=False))


def downgrade() -> None:
    op.drop_column("user_dashboard_widgets", "size_h")
    op.drop_column("user_dashboard_widgets", "size_w")
