"""Discord activity log + message cache.

Listens to Discord events and persists them into ``discord_events``. Also caches
message content into ``discord_message_cache`` so deleted messages can be
recovered by the ticket transcript exporter.

All persistence is best-effort and never raises into discord.py.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import discord
from discord.ext import commands

from config.logging import get_logger
from database.models.discord_event import DiscordEvent, DiscordEventType
from database.models.discord_message_cache import DiscordMessageCache
from database.session import db_session

log = get_logger("bot.activity_log")


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


class ActivityLog(commands.Cog):
    """Persist Discord events for the dashboard's *Discord Log* tab."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    # ---- helpers --------------------------------------------------------

    async def _record(
        self,
        event_type: DiscordEventType,
        *,
        server_id: int | None = None,
        channel_id: int | None = None,
        user_id: int | None = None,
        target_id: int | None = None,
        summary: str = "",
        content: str = "",
        extras: dict[str, Any] | None = None,
    ) -> None:
        try:
            async with db_session() as s:
                s.add(
                    DiscordEvent(
                        created_at=_now(),
                        event_type=event_type,
                        server_id=server_id,
                        channel_id=channel_id,
                        user_id=user_id,
                        target_id=target_id,
                        summary=summary[:500],
                        content=content[:60000],
                        extras=extras or {},
                    )
                )
        except Exception as exc:  # noqa: BLE001
            log.warning("activity_log_persist_failed", error=str(exc))

    async def _cache_message(self, message: discord.Message) -> None:
        if message.author.bot:
            return
        try:
            async with db_session() as s:
                existing = await s.get(DiscordMessageCache, message.id)
                if existing is not None:
                    existing.content = (message.content or "")[:60000]
                    return
                s.add(
                    DiscordMessageCache(
                        message_id=message.id,
                        channel_id=message.channel.id,
                        guild_id=message.guild.id if message.guild else None,
                        author_id=message.author.id,
                        author_name=str(message.author)[:128],
                        content=(message.content or "")[:60000],
                        attachments=[
                            {"url": a.url, "filename": a.filename, "size": a.size}
                            for a in message.attachments
                        ],
                        created_at=message.created_at or _now(),
                    )
                )
        except Exception as exc:  # noqa: BLE001
            log.warning("message_cache_persist_failed", error=str(exc))

    # ---- listeners ------------------------------------------------------

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.guild is None or message.author.bot:
            return
        await self._cache_message(message)
        await self._record(
            DiscordEventType.MESSAGE_SENT,
            server_id=message.guild.id,
            channel_id=message.channel.id,
            user_id=message.author.id,
            summary=f"{message.author} in #{message.channel}",
            content=message.content or "",
            extras={
                "attachments": [a.url for a in message.attachments],
                "message_id": message.id,
            },
        )

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message) -> None:
        if after.guild is None or after.author.bot:
            return
        if before.content == after.content:
            return
        try:
            async with db_session() as s:
                row = await s.get(DiscordMessageCache, after.id)
                if row is not None:
                    row.content = (after.content or "")[:60000]
        except Exception:  # noqa: BLE001
            pass
        await self._record(
            DiscordEventType.MESSAGE_EDITED,
            server_id=after.guild.id,
            channel_id=after.channel.id,
            user_id=after.author.id,
            summary=f"{after.author} edited a message",
            content=after.content or "",
            extras={
                "message_id": after.id,
                "before": before.content or "",
                "channel_name": getattr(after.channel, "name", None),
            },
        )

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message) -> None:
        if message.guild is None:
            return
        try:
            async with db_session() as s:
                row = await s.get(DiscordMessageCache, message.id)
                if row is not None and row.deleted_at is None:
                    row.deleted_at = _now()
        except Exception:  # noqa: BLE001
            pass
        await self._record(
            DiscordEventType.MESSAGE_DELETED,
            server_id=message.guild.id,
            channel_id=message.channel.id,
            user_id=message.author.id if message.author else None,
            summary=f"Message deleted in #{message.channel}",
            content=message.content or "",
            extras={
                "message_id": message.id,
                "attachments": [a.url for a in message.attachments],
                "channel_name": getattr(message.channel, "name", None),
            },
        )

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        await self._record(
            DiscordEventType.MEMBER_JOIN,
            server_id=member.guild.id,
            user_id=member.id,
            summary=f"{member} joined",
        )

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        await self._record(
            DiscordEventType.MEMBER_LEAVE,
            server_id=member.guild.id,
            user_id=member.id,
            summary=f"{member} left",
        )

    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, user: discord.User) -> None:
        await self._record(
            DiscordEventType.MEMBER_BAN,
            server_id=guild.id,
            target_id=user.id,
            summary=f"{user} was banned",
        )

    @commands.Cog.listener()
    async def on_member_unban(self, guild: discord.Guild, user: discord.User) -> None:
        await self._record(
            DiscordEventType.MEMBER_UNBAN,
            server_id=guild.id,
            target_id=user.id,
            summary=f"{user} was unbanned",
        )

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member) -> None:
        before_roles = set(before.roles)
        after_roles = set(after.roles)
        added = after_roles - before_roles
        removed = before_roles - after_roles
        for r in added:
            await self._record(
                DiscordEventType.MEMBER_ROLE_ADDED,
                server_id=after.guild.id,
                user_id=after.id,
                target_id=r.id,
                summary=f"{after}: +{r.name}",
            )
        for r in removed:
            await self._record(
                DiscordEventType.MEMBER_ROLE_REMOVED,
                server_id=after.guild.id,
                user_id=after.id,
                target_id=r.id,
                summary=f"{after}: -{r.name}",
            )

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel: discord.abc.GuildChannel) -> None:
        await self._record(
            DiscordEventType.CHANNEL_CREATED,
            server_id=channel.guild.id,
            channel_id=channel.id,
            summary=f"Channel created: #{channel.name}",
        )

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel) -> None:
        await self._record(
            DiscordEventType.CHANNEL_DELETED,
            server_id=channel.guild.id,
            channel_id=channel.id,
            summary=f"Channel deleted: #{channel.name}",
        )

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        if before.channel is None and after.channel is not None:
            await self._record(
                DiscordEventType.VOICE_JOIN,
                server_id=member.guild.id,
                user_id=member.id,
                channel_id=after.channel.id,
                summary=f"{member} joined voice #{after.channel.name}",
            )
        elif before.channel is not None and after.channel is None:
            await self._record(
                DiscordEventType.VOICE_LEAVE,
                server_id=member.guild.id,
                user_id=member.id,
                channel_id=before.channel.id,
                summary=f"{member} left voice #{before.channel.name}",
            )
        elif before.channel != after.channel and after.channel is not None:
            await self._record(
                DiscordEventType.VOICE_MOVE,
                server_id=member.guild.id,
                user_id=member.id,
                channel_id=after.channel.id,
                summary=f"{member} moved {before.channel.name} → {after.channel.name}"
                if before.channel else f"{member} moved → {after.channel.name}",
            )

    @commands.Cog.listener()
    async def on_app_command_completion(
        self,
        interaction: discord.Interaction,
        command: discord.app_commands.Command,
    ) -> None:
        guild_id = interaction.guild.id if interaction.guild else None
        await self._record(
            DiscordEventType.SLASH_COMMAND,
            server_id=guild_id,
            channel_id=interaction.channel_id,
            user_id=interaction.user.id,
            summary=f"/{command.qualified_name} by {interaction.user}",
            extras={"command": command.qualified_name},
        )

        # FEAT #4/#7: when a slash command is used inside a ticket channel,
        # log it as TICKET_COMMAND and notify the channel for transparency.
        if guild_id is None or interaction.channel_id is None:
            return
        try:
            from sqlalchemy import select
            from database.models.ticket import Ticket
            from database.session import db_session

            async with db_session() as s:
                ticket = await s.scalar(
                    select(Ticket).where(Ticket.channel_id == interaction.channel_id)
                )
            if ticket is None:
                return
            await self._record(
                DiscordEventType.TICKET_COMMAND,
                server_id=guild_id,
                channel_id=interaction.channel_id,
                user_id=interaction.user.id,
                summary=f"/{command.qualified_name} in ticket #{ticket.id}",
                extras={
                    "command": command.qualified_name,
                    "ticket_id": str(ticket.id),
                },
            )
            channel = interaction.channel
            if channel is not None:
                try:
                    await channel.send(
                        f"\N{WRENCH} `/{command.qualified_name}` ausgeführt von "
                        f"{interaction.user.mention}",
                        allowed_mentions=discord.AllowedMentions.none(),
                    )
                except discord.HTTPException:
                    pass
        except Exception:  # noqa: BLE001
            # Logging is best-effort; never break command flow.
            pass


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ActivityLog(bot))
