"""add grid_col/grid_row to user_dashboard_widgets

Revision ID: 0014_widget_position
Revises: 0013_widget_sizes
Create Date: 2026-08-18
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0014_widget_position"
down_revision = "0013_widget_sizes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = [c["name"] for c in inspector.get_columns("user_dashboard_widgets")]
    if "grid_col" not in columns:
        op.add_column("user_dashboard_widgets",
                      sa.Column("grid_col", sa.Integer(), server_default="0", nullable=False))
    if "grid_row" not in columns:
        op.add_column("user_dashboard_widgets",
                      sa.Column("grid_row", sa.Integer(), server_default="0", nullable=False))


def downgrade() -> None:
    op.drop_column("user_dashboard_widgets", "grid_row")
    op.drop_column("user_dashboard_widgets", "grid_col")
