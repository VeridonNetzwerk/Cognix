"""Phase 4: web user permissions + invite tracker + audit details

Revision ID: 0005_phase4
Revises: 0004_phase3
Create Date: 2026-05-15

Idempotent: 0001_initial bootstraps schema via Base.metadata.create_all,
which already materializes columns/tables/indexes that exist on the current
models. Guard each op so re-runs against an already-bootstrapped DB succeed.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005_phase4"
down_revision = "0004_phase3"
branch_labels = None
depends_on = None


def _inspector():
    return sa.inspect(op.get_bind())


def _has_column(table: str, column: str) -> bool:
    insp = _inspector()
    if not insp.has_table(table):
        return False
    return any(c["name"] == column for c in insp.get_columns(table))


def _has_index(table: str, index: str) -> bool:
    insp = _inspector()
    if not insp.has_table(table):
        return False
    return any(ix["name"] == index for ix in insp.get_indexes(table))


def _has_table(table: str) -> bool:
    return _inspector().has_table(table)


def upgrade() -> None:
    # AuditLog.details JSON — may already exist from metadata.create_all in 0001
    if not _has_column("audit_logs", "details"):
        with op.batch_alter_table("audit_logs") as batch:
            batch.add_column(sa.Column("details", sa.JSON(), nullable=True))

    # Index DiscordEvent.event_type for fast log filter
    if not _has_index("discord_events", "ix_discord_events_event_type"):
        op.create_index(
            "ix_discord_events_event_type",
            "discord_events",
            ["event_type"],
            unique=False,
        )

    # Invite stats per server: counts/uses per inviter
    if not _has_table("invite_stats"):
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
    if not _has_table("invite_uses"):
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
    if _has_table("invite_uses"):
        op.drop_table("invite_uses")
    if _has_table("invite_stats"):
        op.drop_table("invite_stats")
    if _has_index("discord_events", "ix_discord_events_event_type"):
        op.drop_index("ix_discord_events_event_type", table_name="discord_events")
    if _has_column("audit_logs", "details"):
        with op.batch_alter_table("audit_logs") as batch:
            batch.drop_column("details")
