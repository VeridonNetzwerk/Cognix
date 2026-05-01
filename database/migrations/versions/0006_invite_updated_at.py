"""Phase 4 hotfix: add missing updated_at columns to invite_uses / invite_stats.

Migration 0005_phase4 created these tables without ``updated_at``, but the
ORM model uses ``TimestampMixin`` which expects both ``created_at`` and
``updated_at``. SQLAlchemy 2.x emits RETURNING on INSERT and includes
``updated_at`` in SELECTs, causing 1054 "Unknown column" errors.

Idempotent: only adds columns/columns missing from the live schema.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0006_invite_updated_at"
down_revision = "0005_phase4"
branch_labels = None
depends_on = None


def _inspector():
    return sa.inspect(op.get_bind())


def _has_column(table: str, column: str) -> bool:
    insp = _inspector()
    if not insp.has_table(table):
        return False
    return any(c["name"] == column for c in insp.get_columns(table))


def _add_updated_at(table: str) -> None:
    if not _inspector().has_table(table):
        return
    if _has_column(table, "updated_at"):
        return
    with op.batch_alter_table(table) as batch:
        batch.add_column(
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            )
        )
    # Ensure created_at exists too (defensive — same TimestampMixin pair)
    if not _has_column(table, "created_at"):
        with op.batch_alter_table(table) as batch:
            batch.add_column(
                sa.Column(
                    "created_at",
                    sa.DateTime(timezone=True),
                    nullable=False,
                    server_default=sa.func.now(),
                )
            )


def upgrade() -> None:
    _add_updated_at("invite_uses")
    _add_updated_at("invite_stats")


def downgrade() -> None:
    for table in ("invite_uses", "invite_stats"):
        if _has_column(table, "updated_at"):
            with op.batch_alter_table(table) as batch:
                batch.drop_column("updated_at")
