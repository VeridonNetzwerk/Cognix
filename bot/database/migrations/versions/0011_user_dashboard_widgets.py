"""add user_dashboard_widgets table

Revision ID: 0011_user_dashboard_widgets
Revises: 0010_server_config_enabled_cogs
Create Date: 2026-08-16
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0011_user_dashboard_widgets"
down_revision = "0010_server_config_enabled_cogs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    tables = inspector.get_table_names()
    if "user_dashboard_widgets" not in tables:
        op.create_table(
            "user_dashboard_widgets",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column(
                "user_id",
                sa.Uuid(),
                sa.ForeignKey("web_users.id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            sa.Column("widget_id", sa.String(64), nullable=False),
            sa.Column("position", sa.Integer(), server_default="0", nullable=False),
            sa.Column("visible", sa.Boolean(), server_default="1", nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("user_id", "widget_id", name="uq_user_widget"),
        )


def downgrade() -> None:
    op.drop_table("user_dashboard_widgets")
