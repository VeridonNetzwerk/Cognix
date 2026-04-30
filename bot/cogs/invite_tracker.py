"""Invite tracker — caches guild invites, attributes new joins to inviter,
and exposes /invites, /inviteinfo, /invitedby slash commands.

Storage: ``invite_stats`` (aggregate per inviter) + ``invite_uses``
(per-join records). Vanity invites and bot-account joins are skipped.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select, update

from config.logging import get_logger
from database import db_session
from database.models.invite_stats import InviteStats
from database.models.invite_uses import InviteUse

log = get_logger("bot.cogs.invite_tracker")


class InviteTracker(commands.Cog):
    """Tracks who invited whom."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        # guild_id -> {invite_code: uses}
        self._cache: dict[int, dict[str, int]] = {}

    # ---------- cache helpers ----------

    async def _refresh_cache(self, guild: discord.Guild) -> None:
        try:
            invites = await guild.invites()
        except (discord.Forbidden, discord.HTTPException):
            return
        self._cache[guild.id] = {inv.code: (inv.uses or 0) for inv in invites}

    async def _bump_stats(
        self,
        *,
        server_id: int,
        inviter_id: int,
        delta_total: int = 0,
        delta_active: int = 0,
        delta_left: int = 0,
        delta_fake: int = 0,
    ) -> None:
        async with db_session() as s:
            row = await s.scalar(
                select(InviteStats).where(
                    InviteStats.server_id == server_id,
                    InviteStats.inviter_id == inviter_id,
                )
            )
            if row is None:
                row = InviteStats(
                    server_id=server_id,
                    inviter_id=inviter_id,
                    total_uses=max(delta_total, 0),
                    active_uses=max(delta_active, 0),
                    left_uses=max(delta_left, 0),
                    fake_uses=max(delta_fake, 0),
                )
                s.add(row)
            else:
                row.total_uses = max(0, row.total_uses + delta_total)
                row.active_uses = max(0, row.active_uses + delta_active)
                row.left_uses = max(0, row.left_uses + delta_left)
                row.fake_uses = max(0, row.fake_uses + delta_fake)
            await s.commit()

    # ---------- listeners ----------

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        for guild in self.bot.guilds:
            await self._refresh_cache(guild)
        log.info("invite_tracker_ready", guilds=len(self._cache))

    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild) -> None:
        await self._refresh_cache(guild)

    @commands.Cog.listener()
    async def on_invite_create(self, invite: discord.Invite) -> None:
        if invite.guild is None:
            return
        bucket = self._cache.setdefault(invite.guild.id, {})
        bucket[invite.code] = invite.uses or 0

    @commands.Cog.listener()
    async def on_invite_delete(self, invite: discord.Invite) -> None:
        if invite.guild is None:
            return
        self._cache.get(invite.guild.id, {}).pop(invite.code, None)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        if member.bot:
            return
        guild = member.guild
        before = self._cache.get(guild.id, {})
        used_code: Optional[str] = None
        inviter_id: Optional[int] = None
        try:
            current = await guild.invites()
        except (discord.Forbidden, discord.HTTPException):
            current = []

        for inv in current:
            prev = before.get(inv.code, 0)
            if (inv.uses or 0) > prev:
                used_code = inv.code
                inviter_id = inv.inviter.id if inv.inviter is not None else None
                break

        # Update cache
        self._cache[guild.id] = {inv.code: (inv.uses or 0) for inv in current}

        # Persist
        async with db_session() as s:
            s.add(
                InviteUse(
                    server_id=guild.id,
                    invitee_id=member.id,
                    inviter_id=inviter_id,
                    code=used_code,
                )
            )
            await s.commit()

        if inviter_id is None:
            return

        # Fake = account younger than 7 days
        is_fake = (
            member.created_at is not None
            and (datetime.now(timezone.utc) - member.created_at).days < 7
        )
        await self._bump_stats(
            server_id=guild.id,
            inviter_id=inviter_id,
            delta_total=1,
            delta_active=0 if is_fake else 1,
            delta_fake=1 if is_fake else 0,
        )

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        guild = member.guild
        async with db_session() as s:
            row = await s.scalar(
                select(InviteUse)
                .where(
                    InviteUse.server_id == guild.id,
                    InviteUse.invitee_id == member.id,
                    InviteUse.left_at.is_(None),
                )
                .order_by(InviteUse.created_at.desc())
            )
            if row is None or row.inviter_id is None:
                return
            row.left_at = datetime.now(timezone.utc)
            await s.commit()
            inviter_id = row.inviter_id
        await self._bump_stats(
            server_id=guild.id,
            inviter_id=inviter_id,
            delta_active=-1,
            delta_left=1,
        )

    # ---------- slash commands ----------

    invites_group = app_commands.Group(name="invites", description="Invite tracker")

    @invites_group.command(name="me", description="Show your invite stats")
    async def invites_me(self, interaction: discord.Interaction) -> None:
        await self._send_stats(interaction, interaction.user)

    @invites_group.command(name="user", description="Show another user's invite stats")
    @app_commands.describe(user="The user to look up")
    async def invites_user(
        self, interaction: discord.Interaction, user: discord.Member
    ) -> None:
        await self._send_stats(interaction, user)

    @invites_group.command(name="leaderboard", description="Top inviters in this server")
    async def invites_top(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("Guild only.", ephemeral=True)
            return
        async with db_session() as s:
            rows = (
                await s.scalars(
                    select(InviteStats)
                    .where(InviteStats.server_id == interaction.guild.id)
                    .order_by(InviteStats.active_uses.desc())
                    .limit(10)
                )
            ).all()
        if not rows:
            await interaction.response.send_message("No invite data yet.", ephemeral=True)
            return
        lines = []
        for i, r in enumerate(rows, 1):
            user = interaction.guild.get_member(r.inviter_id)
            name = user.display_name if user else f"<@{r.inviter_id}>"
            lines.append(
                f"`{i:>2}.` **{name}** — {r.active_uses} active "
                f"({r.total_uses} total · {r.left_uses} left · {r.fake_uses} fake)"
            )
        embed = discord.Embed(
            title="Top Inviters", description="\n".join(lines), colour=discord.Colour.blurple()
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(
        name="invitedby", description="Show who invited a member"
    )
    @app_commands.describe(user="The member to look up")
    async def invited_by(
        self, interaction: discord.Interaction, user: discord.Member
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("Guild only.", ephemeral=True)
            return
        async with db_session() as s:
            row = await s.scalar(
                select(InviteUse)
                .where(
                    InviteUse.server_id == interaction.guild.id,
                    InviteUse.invitee_id == user.id,
                )
                .order_by(InviteUse.created_at.desc())
            )
        if row is None or row.inviter_id is None:
            await interaction.response.send_message(
                f"No invite record for {user.display_name}.", ephemeral=True
            )
            return
        inviter = interaction.guild.get_member(row.inviter_id)
        inviter_name = inviter.mention if inviter else f"<@{row.inviter_id}>"
        await interaction.response.send_message(
            f"{user.mention} was invited by {inviter_name} (code `{row.code or '—'}`).",
            ephemeral=True,
        )

    async def _send_stats(
        self, interaction: discord.Interaction, user: discord.abc.User
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("Guild only.", ephemeral=True)
            return
        async with db_session() as s:
            row = await s.scalar(
                select(InviteStats).where(
                    InviteStats.server_id == interaction.guild.id,
                    InviteStats.inviter_id == user.id,
                )
            )
        if row is None:
            await interaction.response.send_message(
                f"{user.display_name} has not invited anyone yet.", ephemeral=True
            )
            return
        embed = discord.Embed(
            title=f"Invites · {user.display_name}",
            colour=discord.Colour.blurple(),
        )
        embed.add_field(name="Active", value=str(row.active_uses), inline=True)
        embed.add_field(name="Left", value=str(row.left_uses), inline=True)
        embed.add_field(name="Fake", value=str(row.fake_uses), inline=True)
        embed.add_field(name="Total", value=str(row.total_uses), inline=True)
        embed.set_thumbnail(url=user.display_avatar.url)
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(InviteTracker(bot))
