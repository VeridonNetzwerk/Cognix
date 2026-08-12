"""Ensure role_permissions table exists (idempotent).

Older databases bootstrapped via ``Base.metadata.create_all`` already have
this table. Newer prod environments that diverged need it explicitly
materialised so the BUG #5 web panel can persist permission toggles.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0008_role_permissions"
down_revision = "0007_music_history"
branch_labels = None
depends_on = None


def _has_table(name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(name)


def upgrade() -> None:
    if _has_table("role_permissions"):
        return
    op.create_table(
        "role_permissions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("server_id", sa.BigInteger(), nullable=False),
        sa.Column("discord_role_id", sa.BigInteger(), nullable=False),
        sa.Column("command", sa.String(length=64), nullable=False),
        sa.Column("allowed", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("extras", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["server_id"], ["servers.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "server_id", "discord_role_id", "command", name="uq_role_perm"
        ),
    )


def downgrade() -> None:
    if _has_table("role_permissions"):
        op.drop_table("role_permissions")
