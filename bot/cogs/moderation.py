"""Moderation cog: ban, unban, kick, mute, unmute, warn, purge.

Supports cross-server execution via IPC commands ``moderation.*``.
All actions are persisted in the database via service helpers and
broadcast as events for the dashboard.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from config.logging import get_logger
from database import db_session
from database.models.moderation import ModerationAction, ModerationActionType, Warning_
from bot.utils.embeds import err_embed, ok_embed
from bot.utils.time_parser import humanize_seconds, parse_duration

log = get_logger("bot.cogs.moderation")


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


async def _record(
    *,
    guild_id: int,
    action: ModerationActionType,
    moderator_id: int,
    target_id: int | None,
    reason: str,
    duration: int | None = None,
    affected_count: int = 0,
    channel_id: int | None = None,
    web_user_id: str | None = None,
) -> ModerationAction:
    async with db_session() as s:
        row = ModerationAction(
            server_id=guild_id,
            action_type=action,
            target_id=target_id,
            moderator_id=moderator_id,
            reason=reason or "",
            expires_at=(_now() + timedelta(seconds=duration)) if duration else None,
            affected_count=affected_count,
            channel_id=channel_id,
        )
        if web_user_id:
            import uuid as _uuid

            try:
                row.web_user_id = _uuid.UUID(web_user_id)
            except ValueError:
                pass
        s.add(row)
        await s.flush()
        return row


class Moderation(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        ipc = getattr(bot, "ipc", None)
        if ipc is not None:
            ipc.register("moderation.ban", self._ipc_ban)
            ipc.register("moderation.unban", self._ipc_unban)
            ipc.register("moderation.kick", self._ipc_kick)
            ipc.register("moderation.mute", self._ipc_mute)
            ipc.register("moderation.unmute", self._ipc_unmute)
            ipc.register("moderation.warn", self._ipc_warn)
            ipc.register("moderation.purge", self._ipc_purge)

    # ===================== Slash commands =====================

    @app_commands.command(name="ban", description="Ban a user")
    @app_commands.describe(user="User to ban", reason="Reason", delete_days="Days of messages to delete")
    @app_commands.checks.has_permissions(ban_members=True)
    async def ban(
        self,
        interaction: discord.Interaction,
        user: discord.User,
        reason: str = "",
        delete_days: app_commands.Range[int, 0, 7] = 0,
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("Guild only", ephemeral=True)
            return
        try:
            await interaction.guild.ban(user, reason=reason, delete_message_days=delete_days)
            await _record(
                guild_id=interaction.guild.id,
                action=ModerationActionType.BAN,
                moderator_id=interaction.user.id,
                target_id=user.id,
                reason=reason,
            )
            await interaction.response.send_message(
                embed=ok_embed("User banned", f"{user.mention} – {reason or 'no reason'}"),
                ephemeral=True,
            )
        except discord.HTTPException as exc:
            await interaction.response.send_message(embed=err_embed("Ban failed", str(exc)), ephemeral=True)

    @app_commands.command(name="unban", description="Unban a user")
    @app_commands.describe(user_id="User ID", reason="Reason")
    @app_commands.checks.has_permissions(ban_members=True)
    async def unban(self, interaction: discord.Interaction, user_id: str, reason: str = "") -> None:
        if interaction.guild is None:
            await interaction.response.send_message("Guild only", ephemeral=True)
            return
        try:
            uid = int(user_id)
            await interaction.guild.unban(discord.Object(id=uid), reason=reason)
            await _record(
                guild_id=interaction.guild.id,
                action=ModerationActionType.UNBAN,
                moderator_id=interaction.user.id,
                target_id=uid,
                reason=reason,
            )
            await interaction.response.send_message(embed=ok_embed("User unbanned"), ephemeral=True)
        except (ValueError, discord.HTTPException) as exc:
            await interaction.response.send_message(embed=err_embed("Unban failed", str(exc)), ephemeral=True)

    @app_commands.command(name="kick", description="Kick a member")
    @app_commands.checks.has_permissions(kick_members=True)
    async def kick(
        self, interaction: discord.Interaction, user: discord.Member, reason: str = ""
    ) -> None:
        try:
            await user.kick(reason=reason)
            await _record(
                guild_id=interaction.guild_id or 0,
                action=ModerationActionType.KICK,
                moderator_id=interaction.user.id,
                target_id=user.id,
                reason=reason,
            )
            await interaction.response.send_message(embed=ok_embed("User kicked"), ephemeral=True)
        except discord.HTTPException as exc:
            await interaction.response.send_message(embed=err_embed("Kick failed", str(exc)), ephemeral=True)

    @app_commands.command(name="mute", description="Timeout a member (omit time = max 28d)")
    @app_commands.describe(user="Member", reason="Reason", duration="e.g. 1h30m, 10m, 2d")
    @app_commands.checks.has_permissions(moderate_members=True)
    async def mute(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        reason: str = "",
        duration: str | None = None,
    ) -> None:
        secs = parse_duration(duration)
        # Discord max timeout is 28 days
        max_secs = 28 * 86400
        secs = max_secs if secs is None else min(secs, max_secs)
        until = _now() + timedelta(seconds=secs)
        try:
            await user.timeout(until, reason=reason)
            await _record(
                guild_id=interaction.guild_id or 0,
                action=ModerationActionType.MUTE,
                moderator_id=interaction.user.id,
                target_id=user.id,
                reason=reason,
                duration=secs,
            )
            await interaction.response.send_message(
                embed=ok_embed("Muted", f"{user.mention} for {humanize_seconds(secs)}"),
                ephemeral=True,
            )
        except discord.HTTPException as exc:
            await interaction.response.send_message(embed=err_embed("Mute failed", str(exc)), ephemeral=True)

    @app_commands.command(name="unmute", description="Remove timeout")
    @app_commands.checks.has_permissions(moderate_members=True)
    async def unmute(
        self, interaction: discord.Interaction, user: discord.Member, reason: str = ""
    ) -> None:
        try:
            await user.timeout(None, reason=reason)
            await _record(
                guild_id=interaction.guild_id or 0,
                action=ModerationActionType.UNMUTE,
                moderator_id=interaction.user.id,
                target_id=user.id,
                reason=reason,
            )
            await interaction.response.send_message(embed=ok_embed("Unmuted"), ephemeral=True)
        except discord.HTTPException as exc:
            await interaction.response.send_message(embed=err_embed("Unmute failed", str(exc)), ephemeral=True)

    @app_commands.command(name="warn", description="Warn a user")
    @app_commands.checks.has_permissions(moderate_members=True)
    async def warn(
        self, interaction: discord.Interaction, user: discord.Member, reason: str
    ) -> None:
        async with db_session() as s:
            s.add(
                Warning_(
                    server_id=interaction.guild_id or 0,
                    target_id=user.id,
                    moderator_id=interaction.user.id,
                    reason=reason,
                )
            )
        await _record(
            guild_id=interaction.guild_id or 0,
            action=ModerationActionType.WARN,
            moderator_id=interaction.user.id,
            target_id=user.id,
            reason=reason,
        )
        await interaction.response.send_message(embed=ok_embed("User warned"), ephemeral=True)

    @app_commands.command(name="purge", description="Delete recent messages (optionally by user)")
    @app_commands.describe(count="1–500", user="Filter by user")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def purge(
        self,
        interaction: discord.Interaction,
        count: app_commands.Range[int, 1, 500],
        user: discord.User | None = None,
    ) -> None:
        if not isinstance(interaction.channel, discord.TextChannel | discord.Thread):
            await interaction.response.send_message("Text channels only", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)

        def check(m: discord.Message) -> bool:
            return user is None or m.author.id == user.id

        deleted = await interaction.channel.purge(limit=count, check=check)
        await _record(
            guild_id=interaction.guild_id or 0,
            action=ModerationActionType.PURGE,
            moderator_id=interaction.user.id,
            target_id=user.id if user else None,
            reason="purge",
            affected_count=len(deleted),
            channel_id=interaction.channel.id,
        )
        await interaction.followup.send(
            embed=ok_embed("Purged", f"Deleted {len(deleted)} message(s)."), ephemeral=True
        )

    # ===================== IPC handlers (cross-server) =====================

    async def _ipc_ban(self, p: dict[str, Any]) -> dict[str, Any]:
        return await self._ipc_apply("ban", p)

    async def _ipc_unban(self, p: dict[str, Any]) -> dict[str, Any]:
        return await self._ipc_apply("unban", p)

    async def _ipc_kick(self, p: dict[str, Any]) -> dict[str, Any]:
        return await self._ipc_apply("kick", p)

    async def _ipc_mute(self, p: dict[str, Any]) -> dict[str, Any]:
        return await self._ipc_apply("mute", p)

    async def _ipc_unmute(self, p: dict[str, Any]) -> dict[str, Any]:
        return await self._ipc_apply("unmute", p)

    async def _ipc_warn(self, p: dict[str, Any]) -> dict[str, Any]:
        return await self._ipc_apply("warn", p)

    async def _ipc_purge(self, p: dict[str, Any]) -> dict[str, Any]:
        return await self._ipc_apply("purge", p)

    async def _ipc_apply(self, action: str, p: dict[str, Any]) -> dict[str, Any]:
        results: list[dict[str, Any]] = []
        for sid in p.get("server_ids", []):
            guild = self.bot.get_guild(int(sid))
            if guild is None:
                results.append({"server_id": str(sid), "ok": False, "error": "guild not found"})
                continue
            try:
                await self._apply_in_guild(guild, action, p)
                results.append({"server_id": str(sid), "ok": True})
            except Exception as exc:  # noqa: BLE001
                results.append({"server_id": str(sid), "ok": False, "error": str(exc)})
        return {"results": results}

    async def _apply_in_guild(
        self, guild: discord.Guild, action: str, p: dict[str, Any]
    ) -> None:
        target_id = p.get("target_id")
        reason = p.get("reason") or ""
        moderator_id = 0  # web-initiated
        if action in ("ban", "unban") and target_id is not None:
            obj = discord.Object(id=int(target_id))
            if action == "ban":
                await guild.ban(obj, reason=reason)
                act = ModerationActionType.BAN
            else:
                await guild.unban(obj, reason=reason)
                act = ModerationActionType.UNBAN
            await _record(
                guild_id=guild.id, action=act, moderator_id=moderator_id,
                target_id=int(target_id), reason=reason, web_user_id=p.get("web_user_id"),
            )
            return

        if action in ("kick", "mute", "unmute", "warn") and target_id is not None:
            member = guild.get_member(int(target_id)) or await guild.fetch_member(int(target_id))
            if action == "kick":
                await member.kick(reason=reason)
                act = ModerationActionType.KICK
            elif action == "mute":
                secs = p.get("duration_seconds") or (28 * 86400)
                await member.timeout(_now() + timedelta(seconds=int(secs)), reason=reason)
                act = ModerationActionType.MUTE
                duration = int(secs)
                await _record(
                    guild_id=guild.id, action=act, moderator_id=moderator_id,
                    target_id=member.id, reason=reason, duration=duration,
                    web_user_id=p.get("web_user_id"),
                )
                return
            elif action == "unmute":
                await member.timeout(None, reason=reason)
                act = ModerationActionType.UNMUTE
            else:
                async with db_session() as s:
                    s.add(
                        Warning_(
                            server_id=guild.id, target_id=member.id,
                            moderator_id=moderator_id, reason=reason,
                        )
                    )
                act = ModerationActionType.WARN
            await _record(
                guild_id=guild.id, action=act, moderator_id=moderator_id,
                target_id=member.id, reason=reason, web_user_id=p.get("web_user_id"),
            )
            return

        raise ValueError(f"unsupported action: {action}")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Moderation(bot))
