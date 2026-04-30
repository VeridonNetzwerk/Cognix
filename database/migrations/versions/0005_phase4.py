"""Phase 4: web user permissions + invite tracker + audit details

Revision ID: 0005_phase4
Revises: 0004_phase3
Create Date: 2026-05-15
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005_phase4"
down_revision = "0004_phase3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # AuditLog details JSON (for FEAT #2 — capture context per web action)
    with op.batch_alter_table("audit_logs") as batch:
        batch.add_column(
            sa.Column("details", sa.JSON(), nullable=True)
        )

    # Index DiscordEvent.event_type for fast log filter
    op.create_index(
        "ix_discord_events_event_type", "discord_events", ["event_type"], unique=False,
    )

    # Invite stats per server: counts/uses per inviter
    op.create_table(
        "invite_stats",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("server_id", sa.BigInteger(), nullable=False, index=True),
        sa.Column("inviter_id", sa.BigInteger(), nullable=False, index=True),
        sa.Column("total_uses", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("active_uses", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("left_uses", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("fake_uses", sa.Integer(), nullable=False, server_default="0"),
        sa.UniqueConstraint("server_id", "inviter_id", name="uq_invite_stats"),
    )

    # Per-join record: who invited whom, by which code
    op.create_table(
        "invite_uses",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("server_id", sa.BigInteger(), nullable=False, index=True),
        sa.Column("invitee_id", sa.BigInteger(), nullable=False, index=True),
        sa.Column("inviter_id", sa.BigInteger(), nullable=True, index=True),
        sa.Column("code", sa.String(length=32), nullable=True),
        sa.Column("left_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("invite_uses")
    op.drop_table("invite_stats")
    op.drop_index("ix_discord_events_event_type", table_name="discord_events")
    with op.batch_alter_table("audit_logs") as batch:
        batch.drop_column("details")
