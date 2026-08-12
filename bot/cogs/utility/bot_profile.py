"""Bot Profile cog: manage bot display name, avatar, banner, and presence from Discord."""

from __future__ import annotations

COG_INFO = {
    "name": "Bot Profile",
    "description": "Manage bot display name, avatar, banner, and presence",
    "category": "Administration",
    "requires_admin": True,
}

import discord
from discord import app_commands
from discord.ext import commands

from bot.utils.embeds import err_embed


class BotProfile(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="bot-profile", description="Show the current bot profile")
    async def show_profile(self, interaction: discord.Interaction) -> None:
        from bot.database.models.content.bot_profile import BotProfile
        from bot.database.session import db_session

        try:
            async with db_session() as s:
                prof = await s.get(BotProfile, 1)
                if prof is None:
                    await interaction.response.send_message(
                        embed=err_embed("No profile", "Bot profile has not been configured."), ephemeral=True
                    )
                    return
                emb = discord.Embed(
                    title=prof.display_name or (self.bot.user.display_name if self.bot.user else "CogniX"),
                    description=prof.about_me or "",
                    color=0x60A5FA,
                )
                await interaction.response.send_message(embed=emb, ephemeral=True)
        except Exception:
            await interaction.response.send_message(
                embed=err_embed("Error", "Could not fetch bot profile."), ephemeral=True
            )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(BotProfile(bot))
