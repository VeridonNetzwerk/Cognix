"""add stream announcer tables

Revision ID: 0017_stream_announcer
Revises: 0016_leveling
Create Date: 2026-08-25
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0017_stream_announcer"
down_revision = "0016_leveling"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    tables = inspector.get_table_names()

    if "stream_announcer_configs" not in tables:
        op.create_table(
            "stream_announcer_configs",
            sa.Column("server_id", sa.BigInteger(),
                      sa.ForeignKey("servers.id", ondelete="CASCADE"),
                      primary_key=True),
            sa.Column("enabled", sa.Boolean(), server_default="false", nullable=False),
            sa.Column("announce_channel_id", sa.BigInteger(), nullable=True),
            sa.Column("announce_message", sa.Text(),
                      server_default="🔴 **{user.name}** is now streaming!\n**{stream_title}**\n{stream_url}",
                      nullable=False),
            sa.Column("tracked_platforms", sa.JSON(), server_default="[]", nullable=False),
            sa.Column("tracked_roles", sa.JSON(), server_default="[]", nullable=False),
            sa.Column("ignored_roles", sa.JSON(), server_default="[]", nullable=False),
            sa.Column("streaming_role_id", sa.BigInteger(), nullable=True),
            sa.Column("delete_on_end", sa.Boolean(), server_default="false", nullable=False),
            sa.Column("ping_role_id", sa.BigInteger(), nullable=True),
            sa.Column("cooldown_minutes", sa.Integer(), server_default="60", nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True),
                      server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True),
                      server_default=sa.func.now(), nullable=False),
        )

    if "stream_sessions" not in tables:
        op.create_table(
            "stream_sessions",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("server_id", sa.BigInteger(),
                      sa.ForeignKey("servers.id", ondelete="CASCADE"),
                      nullable=False),
            sa.Column("user_id", sa.BigInteger(), nullable=False),
            sa.Column("platform", sa.String(32), server_default="twitch", nullable=False),
            sa.Column("stream_url", sa.Text(), server_default="", nullable=False),
            sa.Column("stream_title", sa.Text(), server_default="", nullable=False),
            sa.Column("game", sa.String(256), server_default="", nullable=False),
            sa.Column("announce_message_id", sa.BigInteger(), nullable=True),
            sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
            sa.Column("started_at", sa.BigInteger(), nullable=False),
            sa.Column("ended_at", sa.BigInteger(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True),
                      server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True),
                      server_default=sa.func.now(), nullable=False),
            sa.UniqueConstraint("server_id", "user_id", "platform", "started_at",
                                name="uq_stream_sessions_server_user_platform_start"),
        )
        op.create_index(
            "ix_stream_sessions_server_active",
            "stream_sessions",
            ["server_id", "is_active"],
        )


def downgrade() -> None:
    op.drop_index("ix_stream_sessions_server_active", table_name="stream_sessions")
    op.drop_table("stream_sessions")
    op.drop_table("stream_announcer_configs")
