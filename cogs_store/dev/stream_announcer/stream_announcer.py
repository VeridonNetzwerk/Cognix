"""Stream Announcer cog — auto-announces when members go live on any platform.

Detects Discord streaming status (which works for Twitch, YouTube, and any
platform that sets the "Streaming" activity type) and posts a configurable
announcement message with stream details. Supports:
- Per-server enable/disable, channel selection, custom message template
- Platform filtering (twitch, youtube, custom)
- Role filtering (only track certain roles, ignore others)
- Auto-assign a "Streaming" role while live
- Ping a role when announcing
- Cooldown to prevent re-announcing the same stream
- Delete announcement when stream ends
- /stream config, /stream status, /stream test commands
- Dashboard settings page + widgets
"""

from __future__ import annotations

import time
from typing import Any

COG_INFO = {
    "name": "Stream Announcer",
    "description": "Auto-announce when members go live on Twitch, YouTube, or any platform",
    "category": "Utility",
    "requires_admin": False,
    "version": "0.1.0",
}

EMBED_TEMPLATES = [
    {
        "key": "stream_announce",
        "title": "🔴 {user.name} is now live!",
        "description": "**{stream_title}**\n{stream_url}",
        "color": 0x9146FF,
        "footer_text": "Powered by Cognix · Made by 食べ物",
        "thumbnail_url": "{user_avatar}",
    },
    {
        "key": "stream_end",
        "title": "Stream ended",
        "description": "**{user.name}**'s stream has ended. Thanks for watching!",
        "color": 0x6B7280,
        "footer_text": "Powered by Cognix · Made by 食べ物",
    },
]

WIDGETS = [
    {
        "id": "stream_live",
        "title": "Live Now",
        "template": "widgets/stream_live.html",
        "size": "medium",
        "icon": "ph-youtube-logo",
    },
]

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import desc, select

from bot.config.logging import get_logger
from bot.database import db_session
from bot.database.models.stream_announcer.stream_announcer import (
    StreamAnnouncerConfig,
    StreamSession,
)
from bot.utils.embeds import FOOTER_TEXT

log = get_logger("bot.cogs.stream_announcer")


def _detect_platform(activity: discord.Streaming) -> str:
    """Detect the streaming platform from a Discord Streaming activity."""
    url = (activity.url or "").lower()
    name = (activity.name or "").lower()
    if "twitch.tv" in url or "twitch" in name:
        return "twitch"
    if "youtube.com" in url or "youtu.be" in url or "youtube" in name:
        return "youtube"
    return "custom"


def _format_message(
    text: str,
    member: discord.Member,
    activity: discord.Streaming,
    guild: discord.Guild,
) -> str:
    """Replace placeholders in the announcement message."""
    if not isinstance(text, str) or not text:
        return ""
    replacements = {
        "{user.mention}": member.mention,
        "{user.name}": member.display_name,
        "{user.id}": str(member.id),
        "{user}": str(member),
        "{stream_url}": str(activity.url or ""),
        "{stream_title}": str(activity.name or "Untitled Stream"),
        "{game}": str(activity.game or "Unknown"),
        "{guild.name}": guild.name,
        "{guild.member_count}": str(guild.member_count or 0),
    }
    out = text
    for key, val in replacements.items():
        out = out.replace(key, val)
    return out


def _build_announce_embed(
    cfg: StreamAnnouncerConfig,
    member: discord.Member,
    activity: discord.Streaming,
    guild: discord.Guild,
) -> discord.Embed:
    """Build the stream announcement embed."""
    title = _format_message(cfg.announce_message, member, activity, guild)
    platform = _detect_platform(activity)

    platform_icons = {
        "twitch": "https://assets.twitch.tv/favicon.ico",
        "youtube": "https://www.youtube.com/favicon.ico",
        "custom": "",
    }

    embed = discord.Embed(
        title=f"🔴 {member.display_name} is now live!",
        description=title,
        color=0x9146FF,
        timestamp=discord.utils.utcnow(),
    )

    if activity.url:
        embed.url = str(activity.url)

    embed.add_field(
        name="Platform",
        value=platform.title(),
        inline=True,
    )

    if activity.game:
        embed.add_field(
            name="Category",
            value=str(activity.game),
            inline=True,
        )

    embed.add_field(
        name="Watch",
        value=f"[Click here]({activity.url})" if activity.url else "No URL",
        inline=True,
    )

    embed.set_thumbnail(url=str(member.display_avatar.url))
    embed.set_footer(text=FOOTER_TEXT)
    return embed


class StreamAnnouncer(commands.Cog):
    """Auto-announces when members start streaming."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def _get_config(self, guild_id: int) -> StreamAnnouncerConfig | None:
        async with db_session() as s:
            return await s.get(StreamAnnouncerConfig, guild_id)

    def _is_tracked(
        self,
        cfg: StreamAnnouncerConfig,
        member: discord.Member,
        platform: str,
    ) -> bool:
        """Check if a member's stream should be tracked."""
        if member.bot:
            return False

        # Platform filter
        tracked_platforms = cfg.tracked_platforms or []
        if tracked_platforms and platform not in tracked_platforms:
            return False

        # Ignored roles
        ignored_roles = cfg.ignored_roles or []
        if any(r.id in ignored_roles for r in member.roles):
            return False

        # Tracked roles (empty = everyone)
        tracked_roles = cfg.tracked_roles or []
        if tracked_roles and not any(r.id in tracked_roles for r in member.roles):
            return False

        return True

    async def _check_cooldown(
        self,
        cfg: StreamAnnouncerConfig,
        server_id: int,
        user_id: int,
    ) -> bool:
        """Returns True if we can announce (not on cooldown)."""
        async with db_session() as s:
            last_session = await s.scalar(
                select(StreamSession)
                .where(
                    StreamSession.server_id == server_id,
                    StreamSession.user_id == user_id,
                )
                .order_by(desc(StreamSession.started_at))
                .limit(1)
            )
            if last_session is None:
                return True
            now = int(time.time())
            elapsed = now - last_session.started_at
            return elapsed >= cfg.cooldown_minutes * 60

    async def _end_stream(
        self,
        guild: discord.Guild,
        session: StreamSession,
        cfg: StreamAnnouncerConfig,
    ) -> None:
        """Handle stream end: delete message, remove role, mark session ended."""
        if session.announce_message_id and cfg.delete_on_end:
            channel = guild.get_channel(cfg.announce_channel_id) if cfg.announce_channel_id else None
            if isinstance(channel, discord.TextChannel):
                try:
                    msg = await channel.fetch_message(session.announce_message_id)
                    await msg.delete()
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    pass

        if cfg.streaming_role_id:
            member = guild.get_member(session.user_id)
            if member:
                role = guild.get_role(cfg.streaming_role_id)
                if role:
                    try:
                        await member.remove_roles(role)
                    except (discord.Forbidden, discord.HTTPException):
                        pass

        async with db_session() as s:
            db_session_obj = await s.get(StreamSession, session.id)
            if db_session_obj and db_session_obj.is_active:
                db_session_obj.is_active = False
                db_session_obj.ended_at = int(time.time())

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member) -> None:
        """Detect streaming status changes."""
        before_stream = discord.utils.get(before.activities, type=discord.ActivityType.streaming)
        after_stream = discord.utils.get(after.activities, type=discord.ActivityType.streaming)

        # Stream started
        if before_stream is None and after_stream is not None:
            await self._handle_stream_start(after, after_stream)
        # Stream ended
        elif before_stream is not None and after_stream is None:
            await self._handle_stream_end(before, before_stream)

    async def _handle_stream_start(
        self,
        member: discord.Member,
        activity: discord.Streaming,
    ) -> None:
        guild = member.guild
        cfg = await self._get_config(guild.id)
        if cfg is None or not cfg.enabled:
            return
        if not cfg.announce_channel_id:
            return

        platform = _detect_platform(activity)
        if not self._is_tracked(cfg, member, platform):
            return

        if not await self._check_cooldown(cfg, guild.id, member.id):
            return

        channel = guild.get_channel(cfg.announce_channel_id)
        if not isinstance(channel, discord.TextChannel):
            return

        content = None
        if cfg.ping_role_id:
            role = guild.get_role(cfg.ping_role_id)
            if role:
                content = role.mention

        embed = _build_announce_embed(cfg, member, activity, guild)
        try:
            msg = await channel.send(content=content, embed=embed)
        except (discord.Forbidden, discord.HTTPException) as exc:
            log.warning("stream_announce_send_failed", error=str(exc))
            return

        # Add streaming role
        if cfg.streaming_role_id:
            role = guild.get_role(cfg.streaming_role_id)
            if role:
                try:
                    await member.add_roles(role)
                except (discord.Forbidden, discord.HTTPException):
                    pass

        # Record session
        now = int(time.time())
        async with db_session() as s:
            session = StreamSession(
                server_id=guild.id,
                user_id=member.id,
                platform=platform,
                stream_url=str(activity.url or ""),
                stream_title=str(activity.name or ""),
                game=str(activity.game or ""),
                announce_message_id=msg.id,
                is_active=True,
                started_at=now,
            )
            s.add(session)

    async def _handle_stream_end(
        self,
        member: discord.Member,
        activity: discord.Streaming,
    ) -> None:
        guild = member.guild
        cfg = await self._get_config(guild.id)
        if cfg is None:
            return

        async with db_session() as s:
            session = await s.scalar(
                select(StreamSession).where(
                    StreamSession.server_id == guild.id,
                    StreamSession.user_id == member.id,
                    StreamSession.is_active.is_(True),
                )
            )
            if session is None:
                return
            await self._end_stream(guild, session, cfg)

    # ---------- Slash commands ----------

    group = app_commands.Group(name="stream", description="Stream announcer commands")

    @group.command(name="status", description="Show current stream announcer status")
    @app_commands.guild_only()
    async def stream_status(self, interaction: discord.Interaction) -> None:
        cfg = await self._get_config(interaction.guild_id)
        if cfg is None or not cfg.enabled:
            await interaction.response.send_message(
                "Stream announcer is not configured for this server.",
                ephemeral=True,
            )
            return

        async with db_session() as s:
            active = (await s.scalars(
                select(StreamSession).where(
                    StreamSession.server_id == interaction.guild_id,
                    StreamSession.is_active.is_(True),
                )
            )).all()

        channel = interaction.guild.get_channel(cfg.announce_channel_id) if cfg.announce_channel_id else None
        embed = discord.Embed(
            title="Stream Announcer Status",
            color=0x9146FF,
            timestamp=discord.utils.utcnow(),
        )
        embed.add_field(name="Enabled", value="✅ Yes" if cfg.enabled else "❌ No", inline=True)
        embed.add_field(name="Channel", value=channel.mention if channel else "Not set", inline=True)
        embed.add_field(name="Active Streams", value=str(len(active)), inline=True)
        embed.add_field(
            name="Platforms",
            value=", ".join(cfg.tracked_platforms) if cfg.tracked_platforms else "All",
            inline=True,
        )
        embed.add_field(name="Cooldown", value=f"{cfg.cooldown_minutes} min", inline=True)
        embed.add_field(
            name="Streaming Role",
            value=f"<@&{cfg.streaming_role_id}>" if cfg.streaming_role_id else "None",
            inline=True,
        )
        embed.set_footer(text=FOOTER_TEXT)
        await interaction.response.send_message(embed=embed)

    @group.command(name="toggle", description="Enable or disable stream announcer")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def stream_toggle(
        self,
        interaction: discord.Interaction,
        enabled: bool,
    ) -> None:
        async with db_session() as s:
            cfg = await s.get(StreamAnnouncerConfig, interaction.guild_id)
            if cfg is None:
                cfg = StreamAnnouncerConfig(server_id=interaction.guild_id)
                s.add(cfg)
            cfg.enabled = enabled
        await interaction.response.send_message(
            f"Stream announcer {'enabled' if enabled else 'disabled'}.",
            ephemeral=True,
        )

    @group.command(name="test", description="Send a test stream announcement")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def stream_test(self, interaction: discord.Interaction) -> None:
        cfg = await self._get_config(interaction.guild_id)
        if cfg is None or not cfg.enabled or not cfg.announce_channel_id:
            await interaction.response.send_message(
                "Stream announcer is not configured. Set it up in the dashboard first.",
                ephemeral=True,
            )
            return

        channel = interaction.guild.get_channel(cfg.announce_channel_id)
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message(
                "Announcement channel not found.",
                ephemeral=True,
            )
            return

        class FakeStreaming:
            name = "Test Stream Title"
            url = "https://twitch.tv/test"
            game = "Just Chatting"

        embed = _build_announce_embed(cfg, interaction.user, FakeStreaming(), interaction.guild)
        try:
            await channel.send(embed=embed)
            await interaction.response.send_message(
                f"Test announcement sent to {channel.mention}.",
                ephemeral=True,
            )
        except (discord.Forbidden, discord.HTTPException) as exc:
            await interaction.response.send_message(
                f"Failed to send test: {exc}",
                ephemeral=True,
            )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(StreamAnnouncer(bot))
