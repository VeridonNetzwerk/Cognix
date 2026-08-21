"""Tests for the leveling system — models, XP calculation, level formula.

Tests:
- LevelingConfig defaults
- LevelingUser creation and fields
- LevelingRoleReward uniqueness
- _xp_for_level formula correctness
- _level_from_xp inverse calculation
- _progress_bar rendering
- _format_message placeholder replacement
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from bot.database.models.leveling.leveling import (
    LevelingConfig,
    LevelingRoleReward,
    LevelingUser,
)


class TestLevelingConfigModel:
    """LevelingConfig defaults and creation."""

    async def test_create_config_with_defaults(self, db_sessionmaker):
        async with db_sessionmaker() as s:
            cfg = LevelingConfig(server_id=12345)
            s.add(cfg)
            await s.commit()

            loaded = await s.get(LevelingConfig, 12345)
            assert loaded is not None
            assert loaded.enabled is False
            assert loaded.xp_per_message_min == 15
            assert loaded.xp_per_message_max == 25
            assert loaded.cooldown_seconds == 60
            assert loaded.formula_base == 100
            assert loaded.formula_multiplier == 50
            assert loaded.formula_exponent == 10
            assert loaded.levelup_dm is False
            assert loaded.xp_multiplier == 1.0
            assert loaded.stack_rewards is False
            assert loaded.ignored_channels == []
            assert loaded.ignored_roles == []

    async def test_config_primary_key_is_server_id(self, db_sessionmaker):
        async with db_sessionmaker() as s:
            cfg = LevelingConfig(server_id=99999)
            s.add(cfg)
            await s.commit()

            loaded = await s.get(LevelingConfig, 99999)
            assert loaded is not None
            assert loaded.server_id == 99999


class TestLevelingUserModel:
    """LevelingUser creation and fields."""

    async def test_create_user(self, db_sessionmaker):
        async with db_sessionmaker() as s:
            user = LevelingUser(server_id=123, user_id=456, xp=100, level=2, messages=10)
            s.add(user)
            await s.commit()

            loaded = await s.scalar(
                select(LevelingUser).where(
                    LevelingUser.server_id == 123,
                    LevelingUser.user_id == 456,
                )
            )
            assert loaded is not None
            assert loaded.xp == 100
            assert loaded.level == 2
            assert loaded.messages == 10

    async def test_user_defaults(self, db_sessionmaker):
        async with db_sessionmaker() as s:
            user = LevelingUser(server_id=123, user_id=789)
            s.add(user)
            await s.commit()

            loaded = await s.scalar(
                select(LevelingUser).where(
                    LevelingUser.server_id == 123,
                    LevelingUser.user_id == 789,
                )
            )
            assert loaded is not None
            assert loaded.xp == 0
            assert loaded.level == 0
            assert loaded.messages == 0
            assert loaded.last_xp_at is None

    async def test_unique_server_user_constraint(self, db_sessionmaker):
        async with db_sessionmaker() as s:
            u1 = LevelingUser(server_id=100, user_id=200)
            s.add(u1)
            await s.commit()

        async with db_sessionmaker() as s:
            u2 = LevelingUser(server_id=100, user_id=200)
            s.add(u2)
            with pytest.raises(Exception):
                await s.commit()


class TestLevelingRoleRewardModel:
    """LevelingRoleReward uniqueness and creation."""

    async def test_create_reward(self, db_sessionmaker):
        async with db_sessionmaker() as s:
            reward = LevelingRoleReward(
                server_id=123, level=5, role_id=999, role_name="Level 5"
            )
            s.add(reward)
            await s.commit()

            loaded = await s.scalar(
                select(LevelingRoleReward).where(
                    LevelingRoleReward.server_id == 123,
                    LevelingRoleReward.level == 5,
                )
            )
            assert loaded is not None
            assert loaded.role_id == 999
            assert loaded.role_name == "Level 5"

    async def test_unique_server_level_constraint(self, db_sessionmaker):
        async with db_sessionmaker() as s:
            r1 = LevelingRoleReward(server_id=100, level=10, role_id=200, role_name="Test")
            s.add(r1)
            await s.commit()

        async with db_sessionmaker() as s:
            r2 = LevelingRoleReward(server_id=100, level=10, role_id=300, role_name="Other")
            s.add(r2)
            with pytest.raises(Exception):
                await s.commit()


class TestXPFormula:
    """_xp_for_level and _level_from_xp calculations."""

    def _make_cfg(self, base=100, multiplier=50, exponent=10):
        cfg = LevelingConfig(
            server_id=1,
            formula_base=base,
            formula_multiplier=multiplier,
            formula_exponent=exponent,
        )
        return cfg

    def test_xp_for_level_0(self):
        from cogs_store.dev.leveling.leveling import _xp_for_level
        cfg = self._make_cfg()
        assert _xp_for_level(0, cfg) == 100

    def test_xp_for_level_1(self):
        from cogs_store.dev.leveling.leveling import _xp_for_level
        cfg = self._make_cfg()
        # 100 + 1*50 + 1*10 = 160
        assert _xp_for_level(1, cfg) == 160

    def test_xp_for_level_5(self):
        from cogs_store.dev.leveling.leveling import _xp_for_level
        cfg = self._make_cfg()
        # 100 + 5*50 + 25*10 = 100 + 250 + 250 = 600
        assert _xp_for_level(5, cfg) == 600

    def test_xp_for_level_10(self):
        from cogs_store.dev.leveling.leveling import _xp_for_level
        cfg = self._make_cfg()
        # 100 + 10*50 + 100*10 = 100 + 500 + 1000 = 1600
        assert _xp_for_level(10, cfg) == 1600

    def test_level_from_xp_zero(self):
        from cogs_store.dev.leveling.leveling import _level_from_xp
        cfg = self._make_cfg()
        assert _level_from_xp(0, cfg) == 0

    def test_level_from_xp_below_level_1(self):
        from cogs_store.dev.leveling.leveling import _level_from_xp
        cfg = self._make_cfg()
        assert _level_from_xp(150, cfg) == 0

    def test_level_from_xp_at_level_1(self):
        from cogs_store.dev.leveling.leveling import _level_from_xp
        cfg = self._make_cfg()
        assert _level_from_xp(160, cfg) == 1

    def test_level_from_xp_between_levels(self):
        from cogs_store.dev.leveling.leveling import _level_from_xp
        cfg = self._make_cfg()
        # level 4 needs 100+4*50+16*10 = 410, level 5 needs 600
        assert _level_from_xp(500, cfg) == 4

    def test_level_from_xp_high(self):
        from cogs_store.dev.leveling.leveling import _level_from_xp
        cfg = self._make_cfg()
        assert _level_from_xp(1600, cfg) == 10

    def test_level_round_trip(self):
        """level_from_xp(xp_for_level(n)) == n for various n."""
        from cogs_store.dev.leveling.leveling import _level_from_xp, _xp_for_level
        cfg = self._make_cfg()
        for level in [0, 1, 5, 10, 20, 50]:
            xp = _xp_for_level(level, cfg)
            assert _level_from_xp(xp, cfg) == level


class TestProgressBar:
    """_progress_bar rendering."""

    def test_progress_bar_zero(self):
        from cogs_store.dev.leveling.leveling import _progress_bar
        bar = _progress_bar(0, 100)
        assert "░" in bar
        assert "█" not in bar

    def test_progress_bar_full(self):
        from cogs_store.dev.leveling.leveling import _progress_bar
        bar = _progress_bar(100, 100)
        assert "█" in bar
        assert "░" not in bar

    def test_progress_bar_half(self):
        from cogs_store.dev.leveling.leveling import _progress_bar
        bar = _progress_bar(50, 100, length=20)
        filled = bar.count("█")
        empty = bar.count("░")
        assert filled == 10
        assert empty == 10

    def test_progress_bar_zero_total(self):
        from cogs_store.dev.leveling.leveling import _progress_bar
        bar = _progress_bar(50, 0)
        assert "█" in bar


class TestFormatMessage:
    """_format_message placeholder replacement."""

    def test_format_user_mention(self):
        from cogs_store.dev.leveling.leveling import _format_message

        class FakeMember:
            mention = "<@123>"
            name = "TestUser"
            id = 123

            class FakeGuild:
                name = "TestGuild"
                member_count = 100

            guild = FakeGuild()

        result = _format_message("Hello {user.mention}!", FakeMember(), 5)
        assert result == "Hello <@123>!"

    def test_format_level(self):
        from cogs_store.dev.leveling.leveling import _format_message

        class FakeMember:
            mention = "<@123>"
            name = "TestUser"

            class FakeGuild:
                name = "TestGuild"
                member_count = 100

            guild = FakeGuild()

        result = _format_message("Level {level} reached", FakeMember(), 10)
        assert result == "Level 10 reached"

    def test_format_guild_name(self):
        from cogs_store.dev.leveling.leveling import _format_message

        class FakeMember:
            mention = "<@123>"
            name = "TestUser"

            class FakeGuild:
                name = "My Server"
                member_count = 42

            guild = FakeGuild()

        result = _format_message("Welcome to {guild.name}", FakeMember(), 1)
        assert result == "Welcome to My Server"

    def test_format_multiple_placeholders(self):
        from cogs_store.dev.leveling.leveling import _format_message

        class FakeMember:
            mention = "<@999>"
            name = "Alice"

            class FakeGuild:
                name = "Cool Server"
                member_count = 500

            guild = FakeGuild()

        result = _format_message(
            "{user.mention} reached level {level} in {guild.name}!",
            FakeMember(),
            7,
        )
        assert result == "<@999> reached level 7 in Cool Server!"
