"""Admin cog — lazy cog management commands.

Provides `/admin cog` slash command group for dynamically loading, unloading,
and managing cogs at runtime. This is the primary user-facing interface for
the Lazy Cog Loading System.

Commands:
    /admin cog list              — List all available cogs with their load status
    /admin cog load <name>       — Load a specific cog
    /admin cog unload <name>     — Unload a specific cog  
    /admin cog reload <name>     — Reload a specific cog
    /admin cog enable <server> <cog>  — Enable cog on a specific server
    /admin cog disable <server> <cog> — Disable cog on a specific server

Permissions: Only the bot owner or guild owner can use these commands.
"""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select

from bot.cogs.registry import (
    AVAILABLE_COGS,
    get_all_cog_info,
    get_loaded_cogs,
    load_cog,
    reload_cog,
    unload_cog,
)
from bot.config.logging import get_logger
from bot.database import db_session
from bot.database.models.server_config import ServerConfig

log = get_logger("bot.cogs.admin")


def is_owner() -> app_commands.Check:
    """App-commands compatible owner check."""
    async def predicate(interaction: discord.Interaction) -> bool:
        if interaction.user is None:
            return False
        if await interaction.client.is_owner(interaction.user):
            return True
        if interaction.guild is not None and interaction.guild.owner_id == interaction.user.id:
            return True
        return False
    return app_commands.check(predicate)


class AdminCog(commands.Cog):
    """Admin cog for lazy load management."""

    group = app_commands.Group(name="admin", description="Bot administration commands")
    cog_group = app_commands.Group(name="cog", description="Manage cogs (load/unload/enable/disable)", parent=group)

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    # ------------------------------------------------------------- list

    @cog_group.command(name="list", description="List all available cogs with load status")
    @is_owner()  # Only bot owner
    async def list_cogs(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        cog_infos = get_all_cog_info()
        loaded = get_loaded_cogs()

        lines = []
        for info in cog_infos:
            module = info["module"]
            is_loaded = module in loaded
            status_icon = "🟢" if is_loaded else "⚪"
            admin_req = " (Admin required)" if info.get("requires_admin") else ""
            lines.append(f"{status_icon} **{info['name']}** — {info['description']}{admin_req}")

        lines.insert(0, f"**CogniX Cogs ({len(loaded)}/{len(cog_infos)} loaded)**\n\n")
        await interaction.followup.send("\n".join(lines), ephemeral=True)

    # ------------------------------------------------------------- load

    @cog_group.command(name="load", description="Load a cog dynamically (makes its commands available)")
    @app_commands.describe(cog="The cog to load (e.g. moderation, utility, tickets)")
    @is_owner()
    async def load(self, interaction: discord.Interaction, cog: str) -> None:
        result = await load_cog(self.bot, cog)
        if result.get("ok"):
            # Persist the loaded state
            try:
                from bot.cogs.registry import persist_loaded_cogs
                await persist_loaded_cogs(get_loaded_cogs())
                log.info("cog_persisted", cogs=get_loaded_cogs())
            except Exception as exc:  # noqa: BLE001
                log.warning("cog_persist_failed", error=str(exc))
            await interaction.response.send_message(
                f"✅ **{result['cog']}** loaded successfully.", ephemeral=True
            )
        else:
            await interaction.response.send_message(
                f"❌ {result['error']}", ephemeral=True
            )

    # ------------------------------------------------------------- unload

    @cog_group.command(name="unload", description="Unload a cog (removes its commands)")
    @app_commands.describe(cog="The cog to unload")
    @is_owner()
    async def unload(self, interaction: discord.Interaction, cog: str) -> None:
        result = await unload_cog(self.bot, cog)
        if result.get("ok"):
            try:
                from bot.cogs.registry import persist_loaded_cogs
                await persist_loaded_cogs(get_loaded_cogs())
            except Exception as exc:  # noqa: BLE001
                log.warning("cog_persist_failed", error=str(exc))
            await interaction.response.send_message(
                f"✅ **{result['cog']}** unloaded. Its commands are no longer available.", ephemeral=True
            )
        else:
            await interaction.response.send_message(
                f"❌ {result['error']}", ephemeral=True
            )

    # ------------------------------------------------------------- reload

    @cog_group.command(name="reload", description="Reload a cog (for development)")
    @app_commands.describe(cog="The cog to reload")
    @is_owner()
    async def reload_cog_cmd(self, interaction: discord.Interaction, cog: str) -> None:
        result = await reload_cog(self.bot, cog)
        if result.get("ok"):
            await interaction.response.send_message(
                f"✅ **{result['cog']}** reloaded.", ephemeral=True
            )
        else:
            await interaction.response.send_message(
                f"❌ {result['error']}", ephemeral=True
            )

    # ------------------------------------------------------------- enable/disable per-server

    @cog_group.command(name="enable", description="Enable a cog on a specific server")
    @app_commands.describe(
        server_id="The guild ID to enable for",
        cog="The cog to enable (e.g. moderation, utility)",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def enable_cog(self, interaction: discord.Interaction, server_id: int, cog: str) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)

        # Check if cog exists (accept both short name and full module path)
        cog_info = None
        for c in AVAILABLE_COGS:
            if c["name"].lower() == cog.lower() or c["module"] == f"bot.cogs.{cog}":
                cog_info = c
                break

        if not cog_info:
            await interaction.followup.send(
                f"❌ Unknown cog '{cog}'. Available: {', '.join(c['name'] for c in AVAILABLE_COGS)}", ephemeral=True
            )
            return

        # Update ServerConfig to enable this cog on the server
        async with db_session() as s:
            cfg = await s.scalar(
                select(ServerConfig).where(ServerConfig.server_id == server_id)
            )
            if not cfg:
                await interaction.followup.send("❌ Server not found.", ephemeral=True)
                return

            enabled = cfg.enabled_cogs or []
            if cog not in enabled:
                enabled.append(cog)
                cfg.enabled_cogs = enabled
                await s.flush()

        # Invalidate cache so next command check reflects the change
        try:
            from bot.runtime import invalidate_cog_state_cache
            invalidate_cog_state_cache(server_id=server_id, cog_name=cog.lower())
        except Exception as exc:  # noqa: BLE001
            log.warning("cache_invalidate_failed", error=str(exc))

        await interaction.followup.send(
            f"✅ **{cog_info['name']}** enabled for server `{server_id}`.", ephemeral=True
        )

    @cog_group.command(name="disable", description="Disable a cog on a specific server")
    @app_commands.describe(
        server_id="The guild ID to disable for",
        cog="The cog to disable (e.g. moderation, utility)",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def disable_cog(self, interaction: discord.Interaction, server_id: int, cog: str) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)

        cog_info = None
        for c in AVAILABLE_COGS:
            if c["name"].lower() == cog.lower() or c["module"] == f"bot.cogs.{cog}":
                cog_info = c
                break

        if not cog_info:
            await interaction.followup.send(
                f"❌ Unknown cog '{cog}'. Available: {', '.join(c['name'] for c in AVAILABLE_COGS)}", ephemeral=True
            )
            return

        async with db_session() as s:
            cfg = await s.scalar(
                select(ServerConfig).where(ServerConfig.server_id == server_id)
            )
            if not cfg:
                await interaction.followup.send("❌ Server not found.", ephemeral=True)
                return

            enabled = cfg.enabled_cogs or []
            if cog in enabled:
                enabled.remove(cog)
                cfg.enabled_cogs = enabled
                await s.flush()

        # Invalidate cache so next command check reflects the change
        try:
            from bot.runtime import invalidate_cog_state_cache
            invalidate_cog_state_cache(server_id=server_id, cog_name=cog.lower())
        except Exception as exc:  # noqa: BLE001
            log.warning("cache_invalidate_failed", error=str(exc))

        await interaction.followup.send(
            f"✅ **{cog_info['name']}** disabled for server `{server_id}`.", ephemeral=True
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AdminCog(bot))
