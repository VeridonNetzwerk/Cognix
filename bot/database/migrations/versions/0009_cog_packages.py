"""add cog_packages table for marketplace

Revision ID: 0009_cog_packages
Revises: 0008_role_permissions
Create Date: 2026-08-12
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0009_cog_packages"
down_revision = "0008_role_permissions"
branch_labels = None
depends_on = None


def _has_table(name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(name)


def upgrade() -> None:
    if _has_table("cog_packages"):
        return
    op.create_table(
        "cog_packages",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("display_name", sa.String(length=128), nullable=False),
        sa.Column("description", sa.Text(), server_default="", nullable=False),
        sa.Column("github_repo", sa.String(length=512), server_default="", nullable=False),
        sa.Column("branch", sa.String(length=64), server_default="main", nullable=False),
        sa.Column("version", sa.String(length=32), nullable=True),
        sa.Column("installed_version", sa.String(length=32), nullable=True),
        sa.Column("dependencies", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("category", sa.String(length=64), server_default="General", nullable=False),
        sa.Column("requires_admin", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("author", sa.String(length=128), nullable=True),
        sa.Column("installed", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("install_dir", sa.String(length=512), nullable=True),
        sa.Column("module_name", sa.String(length=256), nullable=True),
        sa.Column(
            "last_installed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "uninstall_requested",
            sa.Boolean(),
            server_default="false",
            nullable=False,
        ),
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
            onupdate=sa.func.now(),
            nullable=False,
        ),
        sa.Index("ix_cog_packages_name", "name"),
    )


def downgrade() -> None:
    if _has_table("cog_packages"):
        op.drop_table("cog_packages")
