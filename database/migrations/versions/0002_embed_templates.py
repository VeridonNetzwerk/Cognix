"""Add embed_templates table.

Revision ID: 0002_embed_templates
Revises: 0001_initial
Create Date: 2026-04-26
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002_embed_templates"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "embed_templates",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "server_id",
            sa.BigInteger(),
            sa.ForeignKey("servers.id", ondelete="CASCADE"),
            nullable=True,
            index=True,
        ),
        sa.Column("key", sa.String(length=64), nullable=False, index=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("title", sa.String(length=256), nullable=False, server_default=""),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("color", sa.Integer(), nullable=False, server_default="6280698"),
        sa.Column("footer_text", sa.String(length=2048), nullable=False, server_default=""),
        sa.Column("footer_icon_url", sa.String(length=512), nullable=False, server_default=""),
        sa.Column("thumbnail_url", sa.String(length=512), nullable=False, server_default=""),
        sa.Column("image_url", sa.String(length=512), nullable=False, server_default=""),
        sa.Column("author_name", sa.String(length=256), nullable=False, server_default=""),
        sa.Column("author_icon_url", sa.String(length=512), nullable=False, server_default=""),
        sa.Column("author_url", sa.String(length=512), nullable=False, server_default=""),
        sa.Column("fields", sa.JSON(), nullable=False),
        sa.Column("extras", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("key", "server_id", name="uq_embed_templates_key_server"),
    )


def downgrade() -> None:
    op.drop_table("embed_templates")
