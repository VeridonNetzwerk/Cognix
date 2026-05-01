"""Add music_play_history table (FEAT #2).

Idempotent: skips create if the table already exists (e.g. after a fresh
``Base.metadata.create_all`` bootstrap).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0007_music_history"
down_revision = "0006_invite_updated_at"
branch_labels = None
depends_on = None


def _has_table(name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(name)


def upgrade() -> None:
    if _has_table("music_play_history"):
        return
    op.create_table(
        "music_play_history",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("server_id", sa.BigInteger(), nullable=False, index=True),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("url", sa.String(length=1024), nullable=False, server_default=""),
        sa.Column("thumbnail", sa.String(length=1024), nullable=False, server_default=""),
        sa.Column("duration", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("played_by", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column(
            "played_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
            index=True,
        ),
    )


def downgrade() -> None:
    if _has_table("music_play_history"):
        op.drop_table("music_play_history")
