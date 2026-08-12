"""Embeds cog: manage and send custom embed templates from Discord."""

from __future__ import annotations

COG_INFO = {
    "name": "Embeds",
    "description": "Create, manage, and send custom embed templates",
    "category": "Utility",
    "requires_admin": True,
}

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select

from bot.utils.embeds import err_embed


class Embeds(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="embed", description="Send a saved embed template by name")
    @app_commands.describe(name="The embed template key/name to send")
    async def embed(self, interaction: discord.Interaction, name: str) -> None:
        from database.models.embed_template import EmbedTemplate
        from database.session import db_session

        try:
            async with db_session() as s:
                row = await s.scalar(
                    select(EmbedTemplate).where(
                        EmbedTemplate.key == name,
                        EmbedTemplate.server_id.is_(None),
                    )
                )
                if row is None:
                    await interaction.response.send_message(
                        embed=err_embed("Not found", f"No embed template named '{name}'."), ephemeral=True
                    )
                    return
                color = row.color if hasattr(row, "color") and row.color else 0x60A5FA
                emb = discord.Embed(
                    title=row.title or "",
                    description=row.description or "",
                    color=color,
                )
                await interaction.response.send_message(embed=emb)
        except Exception:
            await interaction.response.send_message(
                embed=err_embed("Error", "Could not send embed."), ephemeral=True
            )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Embeds(bot))
