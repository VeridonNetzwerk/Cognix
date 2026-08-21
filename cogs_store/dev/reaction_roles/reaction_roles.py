"""Reaction Roles cog: self-assigned roles via emoji reactions.

Provides slash commands to create and manage reaction role messages.
Listens to raw reaction add/remove events to grant or revoke roles.
"""

from __future__ import annotations

COG_INFO = {
    "name": "Reaction Roles",
    "description": "Self-assigned roles via emoji reactions on messages",
    "category": "Utility",
    "requires_admin": True,
    "version": "0.1.0",
}

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select

from bot.config.logging import get_logger
from bot.database import db_session
from bot.database.models.reaction_roles.reaction_role import ReactionRoleMessage
from bot.utils.embeds import err_embed, ok_embed

log = get_logger("bot.cogs.reaction_roles")


class ReactionRoles(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    # ---------- helpers ----------

    async def _find_rr(self, message_id: int) -> ReactionRoleMessage | None:
        async with db_session() as s:
            return await s.scalar(
                select(ReactionRoleMessage).where(
                    ReactionRoleMessage.message_id == message_id
                )
            )

    def _find_mapping(self, rr: ReactionRoleMessage, emoji: str) -> dict | None:
        for m in rr.mappings:
            if m.get("emoji") == emoji:
                return m
        return None

    # ---------- listeners ----------

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent) -> None:
        if payload.guild_id is None or payload.member is None or payload.member.bot:
            return
        rr = await self._find_rr(payload.message_id)
        if rr is None:
            return
        emoji_str = str(payload.emoji)
        mapping = self._find_mapping(rr, emoji_str)
        if mapping is None:
            return
        role_id = mapping.get("role_id")
        if not role_id:
            return
        guild = self.bot.get_guild(payload.guild_id)
        if guild is None:
            return
        role = guild.get_role(role_id)
        if role is None:
            return
        try:
            await payload.member.add_roles(role, reason="Reaction role")
        except discord.HTTPException:
            log.warning("reaction_role_add_failed", role_id=role_id, exc_info=True)

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent) -> None:
        if payload.guild_id is None:
            return
        rr = await self._find_rr(payload.message_id)
        if rr is None:
            return
        emoji_str = str(payload.emoji)
        mapping = self._find_mapping(rr, emoji_str)
        if mapping is None:
            return
        if mapping.get("mode", "toggle") == "sticky":
            return
        role_id = mapping.get("role_id")
        if not role_id:
            return
        guild = self.bot.get_guild(payload.guild_id)
        if guild is None:
            return
        member = guild.get_member(payload.user_id)
        if member is None or member.bot:
            return
        role = guild.get_role(role_id)
        if role is None:
            return
        try:
            await member.remove_roles(role, reason="Reaction role removal")
        except discord.HTTPException:
            log.warning("reaction_role_remove_failed", role_id=role_id, exc_info=True)

    # ---------- commands ----------

    group = app_commands.Group(name="reaction-roles", description="Manage reaction role messages")

    @group.command(name="create", description="Create a reaction role message")
    @app_commands.describe(
        title="Title for the embed",
        description="Description for the embed",
        channel="Channel to post in (defaults to current)",
    )
    @app_commands.checks.has_permissions(manage_roles=True)
    async def create(
        self,
        interaction: discord.Interaction,
        title: str,
        description: str,
        channel: discord.TextChannel | None = None,
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("Guild only", ephemeral=True)
            return
        target = channel or interaction.channel
        if not isinstance(target, discord.TextChannel):
            await interaction.response.send_message("Invalid channel", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)

        embed = discord.Embed(title=title, description=description, color=0x60A5FA)
        embed.set_footer(text="React to get a role · Powered by CogniX")
        msg = await target.send(embed=embed)

        async with db_session() as s:
            rr = ReactionRoleMessage(
                guild_id=interaction.guild.id,
                channel_id=target.id,
                message_id=msg.id,
                title=title,
                description=description,
                mappings=[],
            )
            s.add(rr)

        await interaction.followup.send(
            embed=ok_embed(
                "Reaction role message created",
                f"Message ID: `{msg.id}`\nUse `/reaction-roles add` to map emojis to roles.",
            ),
            ephemeral=True,
        )

    @group.command(name="add", description="Add an emoji→role mapping to a reaction role message")
    @app_commands.describe(
        message_id="The message ID of the reaction role message",
        emoji="Emoji to use (custom: <name:id>, or unicode emoji)",
        role="Role to assign",
        mode="toggle (default) or sticky (add only, no removal)",
    )
    @app_commands.checks.has_permissions(manage_roles=True)
    async def add_mapping(
        self,
        interaction: discord.Interaction,
        message_id: str,
        emoji: str,
        role: discord.Role,
        mode: str = "toggle",
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("Guild only", ephemeral=True)
            return
        if mode not in ("toggle", "sticky"):
            await interaction.response.send_message(
                embed=err_embed("Invalid mode", "Use 'toggle' or 'sticky'."), ephemeral=True
            )
            return
        try:
            msg_id_int = int(message_id)
        except ValueError:
            await interaction.response.send_message(
                embed=err_embed("Invalid message ID"), ephemeral=True
            )
            return

        async with db_session() as s:
            rr = await s.scalar(
                select(ReactionRoleMessage).where(
                    ReactionRoleMessage.message_id == msg_id_int
                )
            )
            if rr is None:
                await interaction.response.send_message(
                    embed=err_embed("Not found", "No reaction role message with that ID."), ephemeral=True
                )
                return
            mappings = list(rr.mappings)
            mappings.append({"emoji": emoji, "role_id": role.id, "mode": mode})
            rr.mappings = mappings
            channel_id = rr.channel_id

        # Add the reaction to the message
        ch = self.bot.get_channel(channel_id)
        if ch is not None:
            try:
                msg_obj = await ch.fetch_message(msg_id_int)
                await msg_obj.add_reaction(emoji)
            except discord.HTTPException:
                log.warning("reaction_role_emoji_add_failed", emoji=emoji, exc_info=True)

        await interaction.response.send_message(
            embed=ok_embed("Mapping added", f"{emoji} → {role.mention} ({mode})"), ephemeral=True
        )

    @group.command(name="list", description="List all reaction role messages in this server")
    @app_commands.checks.has_permissions(manage_roles=True)
    async def list_messages(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("Guild only", ephemeral=True)
            return
        async with db_session() as s:
            rows = (
                await s.execute(
                    select(ReactionRoleMessage).where(
                        ReactionRoleMessage.guild_id == interaction.guild.id
                    )
                )
            ).scalars().all()
        if not rows:
            await interaction.response.send_message(
                embed=ok_embed("No reaction role messages", "Create one with `/reaction-roles create`."),
                ephemeral=True,
            )
            return
        lines = []
        for r in rows:
            count = len(r.mappings)
            lines.append(f"• `{r.message_id}` — {r.title or 'Untitled'} ({count} mappings)")
        await interaction.response.send_message(
            embed=ok_embed("Reaction Role Messages", "\n".join(lines)), ephemeral=True
        )

    @group.command(name="delete", description="Delete a reaction role message")
    @app_commands.describe(message_id="The message ID to remove")
    @app_commands.checks.has_permissions(manage_roles=True)
    async def delete_message(
        self, interaction: discord.Interaction, message_id: str
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("Guild only", ephemeral=True)
            return
        try:
            msg_id_int = int(message_id)
        except ValueError:
            await interaction.response.send_message(
                embed=err_embed("Invalid message ID"), ephemeral=True
            )
            return
        async with db_session() as s:
            rr = await s.scalar(
                select(ReactionRoleMessage).where(
                    ReactionRoleMessage.message_id == msg_id_int
                )
            )
            if rr is None:
                await interaction.response.send_message(
                    embed=err_embed("Not found"), ephemeral=True
                )
                return
            await s.delete(rr)

        await interaction.response.send_message(
            embed=ok_embed("Deleted", "Reaction role message removed from tracking."), ephemeral=True
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ReactionRoles(bot))
