"""Embeds cog: send custom embeds and manage embed templates from Discord."""

from __future__ import annotations

COG_INFO = {
    "name": "Embeds",
    "description": "Send fully custom embeds and manage embed templates",
    "category": "Utility",
    "requires_admin": True,
    "version": "0.2.0",
}

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select

from bot.utils.embeds import FOOTER_TEXT, err_embed
from bot.config.logging import get_logger

log = get_logger("bot.cogs.embeds")


def _apply_footer(embed: discord.Embed) -> discord.Embed:
    """Always set the hardcoded footer on embeds sent by this cog."""
    embed.set_footer(text=FOOTER_TEXT)
    return embed


class Embeds(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    group = app_commands.Group(name="embed", description="Send and manage custom embeds")

    @group.command(name="send", description="Send a fully custom embed to this channel")
    @app_commands.describe(
        title="Embed title",
        description="Embed description (main text)",
        color="Hex color (e.g. #60A5FA) — default: blue",
        thumbnail_url="Thumbnail image URL (top-right small image)",
        image_url="Large image URL (bottom of embed)",
        author_name="Author name shown at top",
        author_icon_url="Small icon next to author name",
        field1_name="Name of field 1",
        field1_value="Value of field 1",
        field1_inline="Field 1 inline?",
        field2_name="Name of field 2",
        field2_value="Value of field 2",
        field2_inline="Field 2 inline?",
        field3_name="Name of field 3",
        field3_value="Value of field 3",
        field3_inline="Field 3 inline?",
    )
    async def embed_send(
        self,
        interaction: discord.Interaction,
        title: str = "",
        description: str = "",
        color: str = "#60A5FA",
        thumbnail_url: str = "",
        image_url: str = "",
        author_name: str = "",
        author_icon_url: str = "",
        field1_name: str = "",
        field1_value: str = "",
        field1_inline: bool = False,
        field2_name: str = "",
        field2_value: str = "",
        field2_inline: bool = False,
        field3_name: str = "",
        field3_value: str = "",
        field3_inline: bool = False,
    ) -> None:
        if not title and not description and not field1_name and not field2_name and not field3_name:
            await interaction.response.send_message(
                embed=err_embed("Missing content", "Provide at least a title, description, or field."),
                ephemeral=True,
            )
            return

        try:
            color_int = int(color.lstrip("#"), 16)
        except ValueError:
            color_int = 0x60A5FA

        emb = discord.Embed(
            title=title or None,
            description=description or None,
            color=color_int,
        )

        if author_name:
            emb.set_author(name=author_name, icon_url=author_icon_url or None)
        if thumbnail_url:
            emb.set_thumbnail(url=thumbnail_url)
        if image_url:
            emb.set_image(url=image_url)

        for fname, fval, finl in (
            (field1_name, field1_value, field1_inline),
            (field2_name, field2_value, field2_inline),
            (field3_name, field3_value, field3_inline),
        ):
            if fname and fval:
                emb.add_field(name=fname, value=fval, inline=finl)

        _apply_footer(emb)
        await interaction.response.send_message(embed=emb)

    @group.command(name="template", description="Send a saved embed template by key")
    @app_commands.describe(key="The embed template key (e.g. ticket_panel, info, welcome)")
    async def embed_template(self, interaction: discord.Interaction, key: str) -> None:
        from bot.database.models.content.embed_template import EmbedTemplate
        from bot.database.session import db_session

        try:
            async with db_session() as s:
                row = await s.scalar(
                    select(EmbedTemplate).where(
                        EmbedTemplate.key == key,
                        EmbedTemplate.server_id.is_(None),
                        EmbedTemplate.enabled.is_(True),
                    )
                )
                if row is None:
                    await interaction.response.send_message(
                        embed=err_embed("Not found", f"No embed template with key '{key}'."), ephemeral=True
                    )
                    return

                color = row.color if row.color else 0x60A5FA
                emb = discord.Embed(
                    title=row.title or None,
                    description=row.description or None,
                    color=color,
                )

                if row.author_name:
                    emb.set_author(
                        name=row.author_name,
                        icon_url=row.author_icon_url or None,
                        url=row.author_url or None,
                    )
                if row.thumbnail_url:
                    emb.set_thumbnail(url=row.thumbnail_url)
                if row.image_url:
                    emb.set_image(url=row.image_url)

                for f in (row.fields or []):
                    if isinstance(f, dict) and f.get("name") and f.get("value"):
                        emb.add_field(
                            name=f["name"],
                            value=f["value"],
                            inline=f.get("inline", False),
                        )

                _apply_footer(emb)
                await interaction.response.send_message(embed=emb)
        except Exception:
            log.warning("embed_template_send_failed", key=key, exc_info=True)
            await interaction.response.send_message(
                embed=err_embed("Error", "Could not send embed template."), ephemeral=True
            )

    @group.command(name="list", description="List all available embed templates")
    async def embed_list(self, interaction: discord.Interaction) -> None:
        from bot.database.models.content.embed_template import EmbedTemplate
        from bot.database.session import db_session

        try:
            async with db_session() as s:
                rows = (await s.scalars(
                    select(EmbedTemplate)
                    .where(EmbedTemplate.server_id.is_(None))
                    .order_by(EmbedTemplate.key)
                )).all()
                if not rows:
                    await interaction.response.send_message(
                        embed=err_embed("No templates", "No embed templates found."), ephemeral=True
                    )
                    return

                emb = discord.Embed(
                    title="Embed Templates",
                    description="\n".join(f"• `{r.key}` — {r.title or '(no title)'}" for r in rows),
                    color=0x60A5FA,
                )
                _apply_footer(emb)
                await interaction.response.send_message(embed=emb, ephemeral=True)
        except Exception:
            log.warning("embed_list_failed", exc_info=True)
            await interaction.response.send_message(
                embed=err_embed("Error", "Could not list templates."), ephemeral=True
            )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Embeds(bot))
