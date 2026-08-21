"""Leveling system models — per-server config, per-user XP, role rewards."""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Boolean,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from bot.database.base import Base, TimestampMixin


class LevelingConfig(Base, TimestampMixin):
    """One row per server. Stores leveling settings."""

    __tablename__ = "leveling_configs"

    server_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("servers.id", ondelete="CASCADE"), primary_key=True
    )

    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # XP settings
    xp_per_message_min: Mapped[int] = mapped_column(Integer, default=15, nullable=False)
    xp_per_message_max: Mapped[int] = mapped_column(Integer, default=25, nullable=False)
    cooldown_seconds: Mapped[int] = mapped_column(Integer, default=60, nullable=False)

    # Level formula: xp_needed = base + (level * multiplier) + (level^2 * exponent)
    # Default: 100 + level*50 + level^2*10  (level 1=160, 2=240, 5=475, 10=1100)
    formula_base: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    formula_multiplier: Mapped[int] = mapped_column(Integer, default=50, nullable=False)
    formula_exponent: Mapped[int] = mapped_column(Integer, default=10, nullable=False)

    # Level-up notification
    levelup_channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    levelup_message: Mapped[str] = mapped_column(
        Text, default="🎉 {user.mention} reached level **{level}**!", nullable=False
    )
    levelup_dm: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # XP multiplier (e.g. 2.0 for double XP weekend, 1.0 for normal)
    xp_multiplier: Mapped[float] = mapped_column(default=1.0, nullable=False)

    # Ignored channels/roles (JSON arrays of IDs)
    ignored_channels: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    ignored_roles: Mapped[list] = mapped_column(JSON, default=list, nullable=False)

    # Stack role rewards (give all roles up to level) vs highest only
    stack_rewards: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class LevelingUser(Base, TimestampMixin):
    """Per-user XP tracking. One row per (server_id, user_id)."""

    __tablename__ = "leveling_users"
    __table_args__ = (
        UniqueConstraint("server_id", "user_id", name="uq_leveling_users_server_user"),
        Index("ix_leveling_users_server_xp", "server_id", "xp"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    server_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("servers.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)

    xp: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    level: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    messages: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    last_xp_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True)


class LevelingRoleReward(Base, TimestampMixin):
    """Role reward for reaching a specific level."""

    __tablename__ = "leveling_role_rewards"
    __table_args__ = (
        UniqueConstraint(
            "server_id", "level", name="uq_leveling_role_rewards_server_level"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    server_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("servers.id", ondelete="CASCADE"), nullable=False
    )
    level: Mapped[int] = mapped_column(Integer, nullable=False)
    role_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    role_name: Mapped[str] = mapped_column(String(256), default="", nullable=False)
