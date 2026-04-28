"""Giveaways cog: time-limited giveaways with reaction-based entry.

Giveaways are persisted to the ``giveaways`` table and are checked every
30 seconds for expiry. When a giveaway ends, winners are drawn from the
\N{PARTY POPPER} reactors of the giveaway message.
"""

from __future__ import annotations

import random
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands, tasks
from sqlalchemy import select

from bot.utils.embeds import err_embed, info_embed, ok_embed
from config.logging import get_logger
from database import db_session
from database.models.giveaway import Giveaway, GiveawayStatus

log = get_logger("bot.cogs.giveaway")
FOOTER_TEXT = "Powered by Cognix \u00b7 Made by \u98df\u3079\u7269"
PARTY = "\N{PARTY POPPER}"

DURATION_RE = re.compile(r"^\s*(\d+)\s*([smhdw])\s*$", re.IGNORECASE)
_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}


def _parse_duration(text: str) -> timedelta | None:
    m = DURATION_RE.match(text)
    if not m:
        return None
    n = int(m.group(1))
    unit = m.group(2).lower()
    if n <= 0 or n > 10_000_000:
        return None
    return timedelta(seconds=n * _UNIT_SECONDS[unit])


def _build_embed(g: Giveaway, ended: bool = False) -> discord.Embed:
    if ended:
        title = f"\N{PARTY POPPER} Giveaway ended: {g.prize}"
        winners = g.winners or []
        if winners:
            mentions = ", ".join(f"<@{int(w)}>" for w in winners)
            description = f"Winners: {mentions}"
        else:
            description = "No valid entries."
        colour = discord.Colour.dark_grey()
    else:
        title = f"\N{PARTY POPPER} Giveaway: {g.prize}"
        description = (
            f"React with {PARTY} to enter!\n"
            f"Winners: **{g.winner_count}**\n"
            f"Ends: <t:{int(g.ends_at.timestamp())}:R>"
        )
        if g.required_role_id:
            description += f"\nRequired role: <@&{g.required_role_id}>"
        colour = discord.Colour.gold()
    embed = discord.Embed(title=title, description=description, colour=colour)
    embed.set_footer(text=FOOTER_TEXT)
    return embed


class Giveaways(commands.Cog):
    group = app_commands.Group(name="giveaway", description="Giveaway commands")

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._tick.start()

    def cog_unload(self) -> None:
        self._tick.cancel()

    @tasks.loop(seconds=30.0)
    async def _tick(self) -> None:
        try:
            now = datetime.now(tz=timezone.utc)
            async with db_session() as s:
                rows = (
                    await s.scalars(
                        select(Giveaway).where(
                            Giveaway.ended.is_(False),
                            Giveaway.status == GiveawayStatus.ACTIVE,
                            Giveaway.ends_at <= now,
                        )
                    )
                ).all()
            for g in rows:
                try:
                    await self._end_giveaway(g.id)
                except Exception as exc:  # noqa: BLE001
                    log.warning("giveaway_end_failed", id=str(g.id), error=str(exc))
        except Exception as exc:  # noqa: BLE001
            log.warning("giveaway_tick_failed", error=str(exc))

    @_tick.before_loop
    async def _before(self) -> None:
        await self.bot.wait_until_ready()

    async def _draw_winners(
        self, g: Giveaway, channel: discord.abc.MessageableChannel
    ) -> list[int]:
        try:
            message = await channel.fetch_message(g.message_id)
        except discord.NotFound:
            return []
        eligible: list[discord.User | discord.Member] = []
        for reaction in message.reactions:
            if str(reaction.emoji) != PARTY:
                continue
            async for user in reaction.users():
                if user.bot:
                    continue
                if g.required_role_id and isinstance(user, discord.Member):
                    if not any(r.id == g.required_role_id for r in user.roles):
                        continue
                eligible.append(user)
        if not eligible:
            return []
        random.shuffle(eligible)
        winners = eligible[: max(1, g.winner_count)]
        return [u.id for u in winners]

    async def _end_giveaway(self, giveaway_id: uuid.UUID) -> Giveaway | None:
        async with db_session() as s:
            g = await s.get(Giveaway, giveaway_id)
            if g is None or g.ended:
                return g
            channel = self.bot.get_channel(g.channel_id)
            if not isinstance(channel, (discord.TextChannel, discord.Thread)):
                g.ended = True
                g.status = GiveawayStatus.ENDED
                return g
            winners = await self._draw_winners(g, channel)
            g.winners = winners
            g.ended = True
            g.status = GiveawayStatus.ENDED
            try:
                msg = await channel.fetch_message(g.message_id)
                await msg.edit(embed=_build_embed(g, ended=True))
            except discord.NotFound:
                pass
            try:
                if winners:
                    mentions = ", ".join(f"<@{w}>" for w in winners)
                    await channel.send(
                        f"\N{PARTY POPPER} Congratulations {mentions}! You won **{g.prize}**.",
                        allowed_mentions=discord.AllowedMentions(users=True),
                    )
                else:
                    await channel.send(
                        f"Giveaway for **{g.prize}** ended with no valid entries."
                    )
            except discord.HTTPException:
                pass
            return g

    # --------------------------------------------------------- commands

    @group.command(name="start", description="Start a new giveaway")
    @app_commands.describe(
        prize="What is being given away",
        duration="Duration (e.g. 30m, 2h, 1d)",
        winners="Number of winners (default 1)",
        required_role="Optional role required to enter",
        channel="Channel to host the giveaway (default current)",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def start(
        self,
        interaction: discord.Interaction,
        prize: str,
        duration: str,
        winners: app_commands.Range[int, 1, 50] = 1,
        required_role: discord.Role | None = None,
        channel: discord.TextChannel | None = None,
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("Guild only", ephemeral=True)
            return
        delta = _parse_duration(duration)
        if delta is None:
            await interaction.response.send_message(
                embed=err_embed("Invalid duration", "Use formats like `30m`, `2h`, `1d`."),
                ephemeral=True,
            )
            return
        target = channel or interaction.channel
        if not isinstance(target, discord.TextChannel):
            await interaction.response.send_message(
                embed=err_embed("Invalid channel", "Pick a regular text channel."),
                ephemeral=True,
            )
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        ends_at = datetime.now(tz=timezone.utc) + delta
        g = Giveaway(
            server_id=interaction.guild.id,
            channel_id=target.id,
            message_id=0,
            prize=prize[:256],
            winner_count=int(winners),
            ends_at=ends_at,
            host_id=interaction.user.id,
            required_role_id=required_role.id if required_role else None,
            winners=[],
        )
        embed = _build_embed(g)
        try:
            msg = await target.send(embed=embed)
            await msg.add_reaction(PARTY)
        except discord.HTTPException as exc:
            await interaction.followup.send(
                embed=err_embed("Failed", str(exc)), ephemeral=True
            )
            return
        g.message_id = msg.id
        async with db_session() as s:
            s.add(g)
        await interaction.followup.send(
            embed=ok_embed("Giveaway started", f"In {target.mention}, ends <t:{int(ends_at.timestamp())}:R>."),
            ephemeral=True,
        )

    @group.command(name="end", description="End a running giveaway immediately")
    @app_commands.describe(message_id="Giveaway message id")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def end(self, interaction: discord.Interaction, message_id: str) -> None:
        try:
            mid = int(message_id)
        except ValueError:
            await interaction.response.send_message(
                embed=err_embed("Invalid", "Message id must be numeric."), ephemeral=True
            )
            return
        async with db_session() as s:
            g = await s.scalar(select(Giveaway).where(Giveaway.message_id == mid))
        if g is None:
            await interaction.response.send_message(
                embed=err_embed("Not found", "No giveaway for that message."), ephemeral=True
            )
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        await self._end_giveaway(g.id)
        await interaction.followup.send(embed=ok_embed("Ended", "Giveaway ended."), ephemeral=True)

    @group.command(name="reroll", description="Reroll winners for an ended giveaway")
    @app_commands.describe(message_id="Giveaway message id")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def reroll(self, interaction: discord.Interaction, message_id: str) -> None:
        try:
            mid = int(message_id)
        except ValueError:
            await interaction.response.send_message(
                embed=err_embed("Invalid", "Message id must be numeric."), ephemeral=True
            )
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        async with db_session() as s:
            g = await s.scalar(select(Giveaway).where(Giveaway.message_id == mid))
            if g is None:
                await interaction.followup.send(
                    embed=err_embed("Not found", "No giveaway for that message."),
                    ephemeral=True,
                )
                return
            channel = self.bot.get_channel(g.channel_id)
            if not isinstance(channel, (discord.TextChannel, discord.Thread)):
                await interaction.followup.send(
                    embed=err_embed("Channel gone", "Original channel not found."),
                    ephemeral=True,
                )
                return
            winners = await self._draw_winners(g, channel)
            g.winners = winners
        if winners:
            mentions = ", ".join(f"<@{w}>" for w in winners)
            try:
                await channel.send(
                    f"\N{PARTY POPPER} New winners for **{g.prize}**: {mentions}",
                    allowed_mentions=discord.AllowedMentions(users=True),
                )
            except discord.HTTPException:
                pass
        await interaction.followup.send(embed=ok_embed("Rerolled", "Winners updated."), ephemeral=True)

    @group.command(name="list", description="List active giveaways for this server")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def list_(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("Guild only", ephemeral=True)
            return
        async with db_session() as s:
            rows = (
                await s.scalars(
                    select(Giveaway).where(
                        Giveaway.server_id == interaction.guild.id,
                        Giveaway.ended.is_(False),
                    )
                )
            ).all()
        if not rows:
            await interaction.response.send_message(
                embed=info_embed("Giveaways", "No active giveaways."), ephemeral=True
            )
            return
        lines = [
            f"\u2022 **{g.prize}** \u2014 ends <t:{int(g.ends_at.timestamp())}:R> "
            f"\u2014 message id `{g.message_id}`"
            for g in rows
        ]
        await interaction.response.send_message(
            embed=info_embed("Active giveaways", "\n".join(lines)),
            ephemeral=True,
        )

    @group.command(name="delete", description="Delete a giveaway record (does not change Discord)")
    @app_commands.describe(message_id="Giveaway message id")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def delete(self, interaction: discord.Interaction, message_id: str) -> None:
        try:
            mid = int(message_id)
        except ValueError:
            await interaction.response.send_message(
                embed=err_embed("Invalid", "Message id must be numeric."), ephemeral=True
            )
            return
        async with db_session() as s:
            g = await s.scalar(select(Giveaway).where(Giveaway.message_id == mid))
            if g is None:
                await interaction.response.send_message(
                    embed=err_embed("Not found", "No giveaway for that message."),
                    ephemeral=True,
                )
                return
            await s.delete(g)
        await interaction.response.send_message(
            embed=ok_embed("Deleted", "Giveaway removed."), ephemeral=True
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Giveaways(bot))
