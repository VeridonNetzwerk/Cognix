"""add leveling tables

Revision ID: 0016_leveling
Revises: 0015_reaction_roles
Create Date: 2026-08-22
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0016_leveling"
down_revision = "0015_reaction_roles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    tables = inspector.get_table_names()

    if "leveling_configs" not in tables:
        op.create_table(
            "leveling_configs",
            sa.Column("server_id", sa.BigInteger(),
                      sa.ForeignKey("servers.id", ondelete="CASCADE"),
                      primary_key=True),
            sa.Column("enabled", sa.Boolean(), server_default="false", nullable=False),
            sa.Column("xp_per_message_min", sa.Integer(), server_default="15", nullable=False),
            sa.Column("xp_per_message_max", sa.Integer(), server_default="25", nullable=False),
            sa.Column("cooldown_seconds", sa.Integer(), server_default="60", nullable=False),
            sa.Column("formula_base", sa.Integer(), server_default="100", nullable=False),
            sa.Column("formula_multiplier", sa.Integer(), server_default="50", nullable=False),
            sa.Column("formula_exponent", sa.Integer(), server_default="10", nullable=False),
            sa.Column("levelup_channel_id", sa.BigInteger(), nullable=True),
            sa.Column("levelup_message", sa.Text(),
                      server_default="🎉 {user.mention} reached level **{level}**!",
                      nullable=False),
            sa.Column("levelup_dm", sa.Boolean(), server_default="false", nullable=False),
            sa.Column("xp_multiplier", sa.Float(), server_default="1.0", nullable=False),
            sa.Column("ignored_channels", sa.JSON(), server_default="[]", nullable=False),
            sa.Column("ignored_roles", sa.JSON(), server_default="[]", nullable=False),
            sa.Column("stack_rewards", sa.Boolean(), server_default="false", nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True),
                      server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True),
                      server_default=sa.func.now(), nullable=False),
        )

    if "leveling_users" not in tables:
        op.create_table(
            "leveling_users",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("server_id", sa.BigInteger(),
                      sa.ForeignKey("servers.id", ondelete="CASCADE"),
                      nullable=False),
            sa.Column("user_id", sa.BigInteger(), nullable=False),
            sa.Column("xp", sa.Integer(), server_default="0", nullable=False),
            sa.Column("level", sa.Integer(), server_default="0", nullable=False),
            sa.Column("messages", sa.Integer(), server_default="0", nullable=False),
            sa.Column("last_xp_at", sa.BigInteger(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True),
                      server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True),
                      server_default=sa.func.now(), nullable=False),
            sa.UniqueConstraint("server_id", "user_id",
                                name="uq_leveling_users_server_user"),
        )
        op.create_index(
            "ix_leveling_users_server_xp",
            "leveling_users",
            ["server_id", "xp"],
        )

    if "leveling_role_rewards" not in tables:
        op.create_table(
            "leveling_role_rewards",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("server_id", sa.BigInteger(),
                      sa.ForeignKey("servers.id", ondelete="CASCADE"),
                      nullable=False),
            sa.Column("level", sa.Integer(), nullable=False),
            sa.Column("role_id", sa.BigInteger(), nullable=False),
            sa.Column("role_name", sa.String(256), server_default="", nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True),
                      server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True),
                      server_default=sa.func.now(), nullable=False),
            sa.UniqueConstraint("server_id", "level",
                                name="uq_leveling_role_rewards_server_level"),
        )


def downgrade() -> None:
    op.drop_table("leveling_role_rewards")
    op.drop_index("ix_leveling_users_server_xp", table_name="leveling_users")
    op.drop_table("leveling_users")
    op.drop_table("leveling_configs")
