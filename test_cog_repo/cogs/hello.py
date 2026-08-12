"""Hello World test cog for CogniX marketplace testing."""

import discord
from discord import app_commands
from discord.ext import commands


class HelloCog(commands.Cog):
    """A simple hello world cog."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="hello", description="Say hello!")
    async def hello(self, interaction: discord.Interaction) -> None:
        """Say hello to the user."""
        await interaction.response.send_message(
            f"Hello, {interaction.user.mention}! 👋 This cog was installed from the marketplace.",
            ephemeral=True,
        )

    @app_commands.command(name="ping", description="Pong!")
    async def ping(self, interaction: discord.Interaction) -> None:
        """Simple ping command."""
        latency = round(self.bot.latency * 1000)
        await interaction.response.send_message(
            f"Pong! 🏓 `{latency}ms`",
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(HelloCog(bot))
