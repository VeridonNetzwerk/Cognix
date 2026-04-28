"""Add discord_events + discord_message_cache + user_settings + module_permissions + bot_profile + playlists tables.

Revision ID: 0003_phase2
Revises: 0002_embed_templates
Create Date: 2026-04-28
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003_phase2"
down_revision = "0002_embed_templates"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Discord activity log
    op.create_table(
        "discord_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("server_id", sa.BigInteger(), nullable=True, index=True),
        sa.Column("channel_id", sa.BigInteger(), nullable=True),
        sa.Column("user_id", sa.BigInteger(), nullable=True, index=True),
        sa.Column("target_id", sa.BigInteger(), nullable=True),
        sa.Column("summary", sa.String(length=512), nullable=False, server_default=""),
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
        sa.Column("extras", sa.JSON(), nullable=False),
    )
    op.create_index(
        "ix_discord_events_server_created", "discord_events", ["server_id", "created_at"]
    )
    op.create_index(
        "ix_discord_events_type_created", "discord_events", ["event_type", "created_at"]
    )

    # Cache full message content so deletes are recoverable for transcripts.
    op.create_table(
        "discord_message_cache",
        sa.Column("message_id", sa.BigInteger(), primary_key=True),
        sa.Column("channel_id", sa.BigInteger(), nullable=False, index=True),
        sa.Column("guild_id", sa.BigInteger(), nullable=True),
        sa.Column("author_id", sa.BigInteger(), nullable=False),
        sa.Column("author_name", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
        sa.Column("attachments", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )

    # User-specific UI settings (theme, font size).
    op.create_table(
        "web_user_settings",
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("web_users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("theme", sa.String(length=32), nullable=False, server_default="dark"),
        sa.Column("accent_color", sa.String(length=16), nullable=False, server_default="#60A5FA"),
        sa.Column("font_size", sa.String(length=16), nullable=False, server_default="medium"),
        sa.Column("extras", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # Granular per-user module permissions.
    op.create_table(
        "web_user_module_permissions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("web_users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("module", sa.String(length=64), nullable=False),
        sa.Column("level", sa.String(length=16), nullable=False, server_default="none"),
        sa.UniqueConstraint("user_id", "module", name="uq_web_user_module"),
    )

    # Per-server cog activation override.
    op.create_table(
        "server_cog_state",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "server_id",
            sa.BigInteger(),
            sa.ForeignKey("servers.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("cog_name", sa.String(length=64), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("server_id", "cog_name", name="uq_server_cog"),
    )

    # Bot profile cache (cosmetic settings managed via dashboard).
    op.create_table(
        "bot_profile",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("display_name", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("about_me", sa.Text(), nullable=False, server_default=""),
        sa.Column("avatar_data", sa.Text(), nullable=False, server_default=""),
        sa.Column("banner_data", sa.Text(), nullable=False, server_default=""),
        sa.Column("activity_type", sa.String(length=16), nullable=False, server_default="playing"),
        sa.Column("activity_text", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="online"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # Music playlists (server-scoped).
    op.create_table(
        "music_playlists",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("server_id", sa.BigInteger(), nullable=False, index=True),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("created_by", sa.BigInteger(), nullable=False),
        sa.Column("tracks", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("server_id", "name", name="uq_music_playlists_server_name"),
    )


def downgrade() -> None:
    op.drop_table("music_playlists")
    op.drop_table("bot_profile")
    op.drop_table("server_cog_state")
    op.drop_table("web_user_module_permissions")
    op.drop_table("web_user_settings")
    op.drop_table("discord_message_cache")
    op.drop_index("ix_discord_events_type_created", table_name="discord_events")
    op.drop_index("ix_discord_events_server_created", table_name="discord_events")
    op.drop_table("discord_events")
