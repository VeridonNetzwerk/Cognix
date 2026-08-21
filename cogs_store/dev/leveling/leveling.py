"""Leveling cog — XP tracking, levels, rank cards, leaderboards, role rewards.

A fancy leveling system with:
- Per-message XP with configurable cooldown
- Customizable level formula
- Level-up messages (channel or DM)
- Role rewards for reaching levels
- XP multiplier (e.g. double XP weekends)
- Ignored channels and roles
- /rank command with progress bar
- /leaderboard command with top members
- /leveling set command for admins to adjust XP
- Dashboard widgets and settings page
"""

from __future__ import annotations

import random
import time
from typing import Any

COG_INFO = {
    "name": "Leveling",
    "description": "Fancy XP-based leveling with role rewards, rank cards, and leaderboards",
    "category": "Fun",
    "requires_admin": False,
    "version": "0.1.0",
}

EMBED_TEMPLATES = [
    {
        "key": "level_up",
        "title": "Level up! 🎉",
        "description": "🎉 {user_mention} reached level **{level}**!",
        "color": 0xFACC15,
        "footer_text": "Powered by Cognix · Made by 食べ物",
    },
    {
        "key": "level_up_dm",
        "title": "Level up! 🎉",
        "description": "You reached level **{level}** in **{guild_name}**!",
        "color": 0xFACC15,
        "footer_text": "Powered by Cognix · Made by 食べ物",
    },
]

WIDGETS = [
    {
        "id": "leveling_top",
        "title": "Top Members",
        "template": "widgets/leveling_top.html",
        "size": "medium",
        "icon": "ph-trophy",
    },
    {
        "id": "leveling_stats",
        "title": "Leveling Stats",
        "template": "widgets/leveling_stats.html",
        "size": "small",
        "icon": "ph-chart-line-up",
    },
]

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import desc, select, func

from bot.config.logging import get_logger
from bot.database import db_session
from bot.database.models.leveling.leveling import (
    LevelingConfig,
    LevelingRoleReward,
    LevelingUser,
)
from bot.utils.embeds import FOOTER_TEXT, err_embed, ok_embed

log = get_logger("bot.cogs.leveling")


def _xp_for_level(level: int, cfg: LevelingConfig) -> int:
    """Calculate total XP needed to reach a given level."""
    return cfg.formula_base + (level * cfg.formula_multiplier) + (level * level * cfg.formula_exponent)


def _level_from_xp(xp: int, cfg: LevelingConfig) -> int:
    """Determine the level for a given total XP amount."""
    level = 0
    while _xp_for_level(level + 1, cfg) <= xp:
        level += 1
    return level


def _progress_bar(current: int, total: int, length: int = 20) -> str:
    """Generate a text-based progress bar."""
    if total <= 0:
        return "█" * length
    filled = int((current / total) * length)
    return "█" * filled + "░" * (length - filled)


def _format_message(text: str, member: discord.Member, level: int) -> str:
    """Replace placeholders in a level-up message."""
    return (
        text.replace("{user.mention}", member.mention)
        .replace("{user.name}", member.name)
        .replace("{user}", str(member))
        .replace("{level}", str(level))
        .replace("{guild.name}", member.guild.name)
        .replace("{guild_name}", member.guild.name)
    )


class Leveling(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def _get_config(self, server_id: int) -> LevelingConfig:
        async with db_session() as s:
            cfg = await s.get(LevelingConfig, server_id)
            if cfg is None:
                cfg = LevelingConfig(server_id=server_id)
                s.add(cfg)
            return cfg

    def _is_ignored(self, cfg: LevelingConfig, member: discord.Member, channel: discord.TextChannel) -> bool:
        if channel.id in (cfg.ignored_channels or []):
            return True
        if any(r.id in (cfg.ignored_roles or []) for r in member.roles):
            return True
        if member.bot:
            return True
        return False

    async def _check_role_rewards(self, member: discord.Member, old_level: int, new_level: int, cfg: LevelingConfig) -> None:
        """Assign role rewards for the new level if applicable."""
        if new_level <= old_level:
            return
        async with db_session() as s:
            rewards = (
                await s.scalars(
                    select(LevelingRoleReward)
                    .where(LevelingRoleReward.server_id == member.guild.id)
                    .where(LevelingRoleReward.level <= new_level)
                    .order_by(desc(LevelingRoleReward.level))
                )
            ).all()
            if not rewards:
                return

            if cfg.stack_rewards:
                target_role_ids = {r.role_id for r in rewards if r.level <= new_level}
            else:
                target_role_ids = {rewards[0].role_id}

            current_role_ids = {r.id for r in member.roles}
            to_add = target_role_ids - current_role_ids
            if not to_add:
                return

            for role_id in to_add:
                role = member.guild.get_role(role_id)
                if role and role.is_assignable():
                    try:
                        await member.add_roles(role, reason=f"Reached level {new_level}")
                    except discord.HTTPException:
                        log.warning("leveling_role_add_failed", role_id=role_id, user_id=member.id)

    async def _send_levelup(self, member: discord.Member, level: int, cfg: LevelingConfig) -> None:
        """Send level-up notification to channel or DM."""
        message = _format_message(cfg.levelup_message, member, level)

        if cfg.levelup_dm:
            try:
                await member.send(message)
            except discord.HTTPException:
                pass
            return

        if cfg.levelup_channel_id:
            channel = member.guild.get_channel(cfg.levelup_channel_id)
            if isinstance(channel, discord.TextChannel):
                try:
                    await channel.send(message)
                except discord.HTTPException:
                    pass

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if not isinstance(message.author, discord.Member) or message.author.bot:
            return
        if not isinstance(message.channel, discord.TextChannel):
            return

        cfg = await self._get_config(message.guild.id)
        if not cfg.enabled:
            return

        if self._is_ignored(cfg, message.author, message.channel):
            return

        now = int(time.time())
        async with db_session() as s:
            user = await s.scalar(
                select(LevelingUser).where(
                    LevelingUser.server_id == message.guild.id,
                    LevelingUser.user_id == message.author.id,
                )
            )
            if user is None:
                user = LevelingUser(
                    server_id=message.guild.id,
                    user_id=message.author.id,
                    xp=0,
                    level=0,
                    messages=0,
                )
                s.add(user)

            if user.last_xp_at and (now - user.last_xp_at) < cfg.cooldown_seconds:
                return

            xp_gain = random.randint(cfg.xp_per_message_min, cfg.xp_per_message_max)
            xp_gain = int(xp_gain * cfg.xp_multiplier)

            old_level = user.level
            user.xp += xp_gain
            user.messages += 1
            user.last_xp_at = now
            new_level = _level_from_xp(user.xp, cfg)
            user.level = new_level

        if new_level > old_level:
            await self._send_levelup(message.author, new_level, cfg)
            await self._check_role_rewards(message.author, old_level, new_level, cfg)

    @app_commands.command(name="rank", description="Show your current level and XP")
    @app_commands.describe(member="Check another member's rank")
    async def rank(self, interaction: discord.Interaction, member: discord.Member | None = None) -> None:
        target = member or interaction.user
        if not isinstance(target, discord.Member):
            await interaction.response.send_message(embed=err_embed("Error", "Could not find that member."), ephemeral=True)
            return

        cfg = await self._get_config(interaction.guild.id)
        async with db_session() as s:
            user = await s.scalar(
                select(LevelingUser).where(
                    LevelingUser.server_id == interaction.guild.id,
                    LevelingUser.user_id == target.id,
                )
            )
            if user is None:
                await interaction.response.send_message(
                    embed=err_embed("No data", f"{target.mention} hasn't earned any XP yet."),
                    ephemeral=True,
                )
                return

            rank_result = await s.scalar(
                select(func.count(LevelingUser.id)).where(
                    LevelingUser.server_id == interaction.guild.id,
                    LevelingUser.xp > user.xp,
                )
            )
            rank_num = (rank_result or 0) + 1

        current_level_xp = _xp_for_level(user.level, cfg)
        next_level_xp = _xp_for_level(user.level + 1, cfg)
        progress = user.xp - current_level_xp
        needed = next_level_xp - current_level_xp
        bar = _progress_bar(progress, needed)

        embed = discord.Embed(
            title=f"Rank #{rank_num}",
            description=f"**{target.display_name}**",
            color=0xFACC15,
        )
        embed.set_thumbnail(url=target.display_avatar.url)
        embed.add_field(name="Level", value=f"**{user.level}**", inline=True)
        embed.add_field(name="XP", value=f"{user.xp:,}", inline=True)
        embed.add_field(name="Messages", value=f"{user.messages:,}", inline=True)
        embed.add_field(
            name=f"Progress to Level {user.level + 1}",
            value=f"`{bar}` {progress:,}/{needed:,} XP",
            inline=False,
        )
        embed.set_footer(text=FOOTER_TEXT)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="leaderboard", description="Show the top members by XP")
    async def leaderboard(self, interaction: discord.Interaction) -> None:
        async with db_session() as s:
            rows = (
                await s.scalars(
                    select(LevelingUser)
                    .where(LevelingUser.server_id == interaction.guild.id)
                    .order_by(desc(LevelingUser.xp))
                    .limit(10)
                )
            ).all()

        if not rows:
            await interaction.response.send_message(
                embed=err_embed("No data", "No one has earned XP yet."),
                ephemeral=True,
            )
            return

        cfg = await self._get_config(interaction.guild.id)
        lines: list[str] = []
        medals = ["🥇", "🥈", "🥉"]
        for i, row in enumerate(rows):
            medal = medals[i] if i < 3 else f"**#{i + 1}**"
            lines.append(f"{medal} <@{row.user_id}> — Level **{row.level}** ({row.xp:,} XP)")

        embed = discord.Embed(
            title="🏆 Leaderboard",
            description="\n".join(lines),
            color=0xFACC15,
        )
        embed.set_footer(text=FOOTER_TEXT)
        await interaction.response.send_message(embed=embed)

    group = app_commands.Group(name="leveling", description="Configure the leveling system")

    @group.command(name="toggle", description="Enable or disable leveling (admin only)")
    @app_commands.describe(enabled="True to enable, False to disable")
    @app_commands.default_permissions(manage_guild=True)
    async def leveling_toggle(self, interaction: discord.Interaction, enabled: bool) -> None:
        async with db_session() as s:
            cfg = await s.get(LevelingConfig, interaction.guild.id)
            if cfg is None:
                cfg = LevelingConfig(server_id=interaction.guild.id, enabled=enabled)
                s.add(cfg)
            else:
                cfg.enabled = enabled
        await interaction.response.send_message(
            embed=ok_embed("Leveling", f"Leveling is now {'**enabled**' if enabled else '**disabled**'}."),
            ephemeral=True,
        )

    @group.command(name="set", description="Set a user's XP (admin only)")
    @app_commands.describe(member="The member to adjust", xp="The new XP value")
    @app_commands.default_permissions(manage_guild=True)
    async def leveling_set(self, interaction: discord.Interaction, member: discord.Member, xp: int) -> None:
        if xp < 0:
            await interaction.response.send_message(embed=err_embed("Error", "XP cannot be negative."), ephemeral=True)
            return
        cfg = await self._get_config(interaction.guild.id)
        new_level = _level_from_xp(xp, cfg)
        async with db_session() as s:
            user = await s.scalar(
                select(LevelingUser).where(
                    LevelingUser.server_id == interaction.guild.id,
                    LevelingUser.user_id == member.id,
                )
            )
            if user is None:
                user = LevelingUser(
                    server_id=interaction.guild.id,
                    user_id=member.id,
                    xp=xp,
                    level=new_level,
                    messages=0,
                )
                s.add(user)
            else:
                user.xp = xp
                user.level = new_level
        await interaction.response.send_message(
            embed=ok_embed("XP Updated", f"{member.mention} now has **{xp:,} XP** (Level {new_level})."),
            ephemeral=True,
        )

    @group.command(name="add", description="Add XP to a user (admin only)")
    @app_commands.describe(member="The member to adjust", xp="Amount of XP to add")
    @app_commands.default_permissions(manage_guild=True)
    async def leveling_add(self, interaction: discord.Interaction, member: discord.Member, xp: int) -> None:
        cfg = await self._get_config(interaction.guild.id)
        async with db_session() as s:
            user = await s.scalar(
                select(LevelingUser).where(
                    LevelingUser.server_id == interaction.guild.id,
                    LevelingUser.user_id == member.id,
                )
            )
            if user is None:
                user = LevelingUser(
                    server_id=interaction.guild.id,
                    user_id=member.id,
                    xp=max(0, xp),
                    level=0,
                    messages=0,
                )
                s.add(user)
            else:
                user.xp = max(0, user.xp + xp)
            user.level = _level_from_xp(user.xp, cfg)
        await interaction.response.send_message(
            embed=ok_embed("XP Added", f"Added **{xp} XP** to {member.mention}. Total: **{user.xp:,} XP** (Level {user.level})."),
            ephemeral=True,
        )

    @group.command(name="reset", description="Reset a user's XP (admin only)")
    @app_commands.describe(member="The member to reset")
    @app_commands.default_permissions(manage_guild=True)
    async def leveling_reset(self, interaction: discord.Interaction, member: discord.Member) -> None:
        async with db_session() as s:
            user = await s.scalar(
                select(LevelingUser).where(
                    LevelingUser.server_id == interaction.guild.id,
                    LevelingUser.user_id == member.id,
                )
            )
            if user:
                user.xp = 0
                user.level = 0
                user.messages = 0
        await interaction.response.send_message(
            embed=ok_embed("Reset", f"{member.mention}'s XP has been reset to 0."),
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Leveling(bot))
