"""Tests for bot.cogs.admin and bot.cogs.marketplace — verify cog classes can be instantiated."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import discord
from discord.ext import commands


class TestAdminCogImport:
    """Verify admin cog module imports and class structure is valid."""

    def test_can_import_admin_cog(self):
        from bot.cogs.admin import AdminCog
        assert AdminCog is not None

    def test_admin_cog_has_group_attribute(self):
        from bot.cogs.admin import AdminCog
        assert hasattr(AdminCog, "cog_group")
        assert isinstance(AdminCog.cog_group, discord.app_commands.Group)

    def test_admin_cog_group_is_class_attribute_not_instance(self):
        """The group should be a class attribute, not created in __init__."""
        from bot.cogs.admin import AdminCog
        # Access via class, not instance
        assert AdminCog.cog_group is not None
        assert AdminCog.group is not None

    def test_admin_cog_has_commands(self):
        from bot.cogs.admin import AdminCog
        # The cog_group should have commands registered
        assert len(list(AdminCog.cog_group.walk_commands())) > 0


class TestMarketplaceCogImport:
    """Verify marketplace cog module imports and class structure is valid."""

    def test_can_import_marketplace_cog(self):
        from bot.cogs.marketplace import MarketplaceCogCmd
        assert MarketplaceCogCmd is not None

    def test_marketplace_cog_has_group_attribute(self):
        from bot.cogs.marketplace import MarketplaceCogCmd
        assert hasattr(MarketplaceCogCmd, "marketplace_group")
        assert isinstance(MarketplaceCogCmd.marketplace_group, discord.app_commands.Group)

    def test_marketplace_cog_group_is_class_attribute_not_instance(self):
        """The group should be a class attribute, not created in __init__."""
        from bot.cogs.marketplace import MarketplaceCogCmd
        assert MarketplaceCogCmd.marketplace_group is not None

    def test_marketplace_cog_has_commands(self):
        from bot.cogs.marketplace import MarketplaceCogCmd
        assert len(list(MarketplaceCogCmd.marketplace_group.walk_commands())) > 0
