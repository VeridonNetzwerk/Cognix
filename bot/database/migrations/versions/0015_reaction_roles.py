"""add reaction_role_messages table

Revision ID: 0015_reaction_roles
Revises: 0014_widget_position
Create Date: 2026-08-20
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0015_reaction_roles"
down_revision = "0014_widget_position"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    tables = inspector.get_table_names()
    if "reaction_role_messages" not in tables:
        op.create_table(
            "reaction_role_messages",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column(
                "guild_id",
                sa.BigInteger(),
                sa.ForeignKey("servers.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("channel_id", sa.BigInteger(), nullable=False),
            sa.Column("message_id", sa.BigInteger(), nullable=False),
            sa.Column("mappings", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("title", sa.String(256), server_default="", nullable=False),
            sa.Column("description", sa.Text(), server_default="", nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
        )
        op.create_index(
            "ix_reaction_roles_guild_message",
            "reaction_role_messages",
            ["guild_id", "message_id"],
        )


def downgrade() -> None:
    op.drop_index("ix_reaction_roles_guild_message", table_name="reaction_role_messages")
    op.drop_table("reaction_role_messages")
