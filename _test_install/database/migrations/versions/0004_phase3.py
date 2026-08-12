"""Phase 3: giveaways + ticket types/panels + server event configs + ticket.ticket_type_id

Revision ID: 0004_phase3
Revises: 0003_phase2
Create Date: 2026-04-28
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0004_phase3"
down_revision = "0003_phase2"
branch_labels = None
depends_on = None


def _has_table(name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(name)


def _has_column(table: str, column: str) -> bool:
    insp = sa.inspect(op.get_bind())
    if not insp.has_table(table):
        return False
    return any(c["name"] == column for c in insp.get_columns(table))


def upgrade() -> None:
    if not _has_table("giveaways"):
        op.create_table(
        "giveaways",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("server_id", sa.BigInteger(), nullable=False, index=True),
        sa.Column("channel_id", sa.BigInteger(), nullable=False),
        sa.Column("message_id", sa.BigInteger(), nullable=False, unique=True, index=True),
        sa.Column("prize", sa.String(length=256), nullable=False),
        sa.Column("winner_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("ended", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="active"),
        sa.Column("winners", sa.JSON(), nullable=False),
        sa.Column("required_role_id", sa.BigInteger(), nullable=True),
        sa.Column("host_id", sa.BigInteger(), nullable=False),
    )

    if not _has_table("ticket_types"):
        op.create_table(
        "ticket_types",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("server_id", sa.BigInteger(), nullable=False, index=True),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("description", sa.String(length=256), nullable=False, server_default=""),
        sa.Column("emoji", sa.String(length=16), nullable=False, server_default=""),
        sa.Column("category_id", sa.BigInteger(), nullable=True),
        sa.Column("ping_role_id", sa.BigInteger(), nullable=True),
        sa.Column("welcome_embed", sa.JSON(), nullable=False),
    )

    if not _has_table("ticket_panels"):
        op.create_table(
        "ticket_panels",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("server_id", sa.BigInteger(), nullable=False, index=True),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("channel_id", sa.BigInteger(), nullable=True),
        sa.Column("message_id", sa.BigInteger(), nullable=True),
        sa.Column("embed", sa.JSON(), nullable=False),
        sa.Column("buttons", sa.JSON(), nullable=False),
    )

    if not _has_table("server_event_configs"):
        op.create_table(
        "server_event_configs",
        sa.Column("server_id", sa.BigInteger(), sa.ForeignKey("servers.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("join_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("join_channel_id", sa.BigInteger(), nullable=True),
        sa.Column("join_embed", sa.JSON(), nullable=False),
        sa.Column("leave_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("leave_channel_id", sa.BigInteger(), nullable=True),
        sa.Column("leave_embed", sa.JSON(), nullable=False),
        sa.Column("boost_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("boost_channel_id", sa.BigInteger(), nullable=True),
        sa.Column("boost_embed", sa.JSON(), nullable=False),
    )

    if not _has_column("tickets", "ticket_type_id"):
        with op.batch_alter_table("tickets") as bop:
            bop.add_column(sa.Column("ticket_type_id", sa.Uuid(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("tickets") as bop:
        bop.drop_column("ticket_type_id")
    op.drop_table("server_event_configs")
    op.drop_table("ticket_panels")
    op.drop_table("ticket_types")
    op.drop_table("giveaways")
