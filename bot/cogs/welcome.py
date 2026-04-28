"""Welcome / leave / boost message cog.

Posts an embed message to a configured channel on member join, leave,
or server boost. Configuration is stored per-server in the
``server_event_configs`` table (managed via the dashboard).

The embed payload is a simple JSON dict with these optional keys:
``title``, ``description``, ``color`` (int), ``image_url``,
``thumbnail_url``, ``footer``. The strings support ``{user}``,
``{user.mention}``, ``{user.name}``, ``{user.id}``, ``{guild.name}``,
``{guild.member_count}`` substitutions.
"""

from __future__ import annotations

from typing import Any

import discord
from discord.ext import commands
from sqlalchemy import select

from config.logging import get_logger
from database import db_session
from database.models.server_event_config import ServerEventConfig

log = get_logger("bot.cogs.welcome")
FOOTER_TEXT = "Powered by Cognix \u00b7 Made by \u98df\u3079\u7269"


def _format(text: str, member: discord.Member | discord.User, guild: discord.Guild) -> str:
    if not isinstance(text, str) or not text:
        return ""
    replacements = {
        "{user.mention}": member.mention,
        "{user.name}": getattr(member, "name", str(member)),
        "{user.id}": str(member.id),
        "{user}": str(member),
        "{guild.name}": guild.name,
        "{guild.member_count}": str(guild.member_count or 0),
    }
    out = text
    for key, val in replacements.items():
        out = out.replace(key, val)
    return out


def _build_embed(
    payload: dict[str, Any], member: discord.Member | discord.User, guild: discord.Guild
) -> discord.Embed | None:
    if not payload:
        return None
    title = _format(payload.get("title", ""), member, guild) or None
    description = _format(payload.get("description", ""), member, guild) or None
    if not title and not description:
        return None
    color_raw = payload.get("color", 0x60A5FA)
    try:
        colour = discord.Colour(int(color_raw))
    except (TypeError, ValueError):
        colour = discord.Colour.blurple()
    embed = discord.Embed(title=title, description=description, colour=colour)
    if payload.get("thumbnail_url"):
        try:
            embed.set_thumbnail(url=str(payload["thumbnail_url"]))
        except Exception:  # noqa: BLE001
            pass
    if payload.get("image_url"):
        try:
            embed.set_image(url=str(payload["image_url"]))
        except Exception:  # noqa: BLE001
            pass
    footer = _format(payload.get("footer", FOOTER_TEXT), member, guild)
    embed.set_footer(text=footer or FOOTER_TEXT)
    return embed


class Welcome(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def _config(self, guild_id: int) -> ServerEventConfig | None:
        async with db_session() as s:
            return await s.scalar(
                select(ServerEventConfig).where(ServerEventConfig.server_id == guild_id)
            )

    async def _post(
        self,
        cfg: ServerEventConfig,
        kind: str,
        member: discord.Member | discord.User,
        guild: discord.Guild,
    ) -> None:
        if kind == "join":
            enabled, channel_id, payload = (
                cfg.join_enabled,
                cfg.join_channel_id,
                cfg.join_embed,
            )
        elif kind == "leave":
            enabled, channel_id, payload = (
                cfg.leave_enabled,
                cfg.leave_channel_id,
                cfg.leave_embed,
            )
        elif kind == "boost":
            enabled, channel_id, payload = (
                cfg.boost_enabled,
                cfg.boost_channel_id,
                cfg.boost_embed,
            )
        else:
            return
        if not enabled or not channel_id:
            return
        channel = guild.get_channel(channel_id)
        if not isinstance(channel, discord.TextChannel):
            return
        embed = _build_embed(payload or {}, member, guild)
        if embed is None:
            return
        try:
            await channel.send(embed=embed)
        except discord.HTTPException as exc:
            log.warning("welcome_send_failed", kind=kind, error=str(exc))

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        cfg = await self._config(member.guild.id)
        if cfg is None:
            return
        await self._post(cfg, "join", member, member.guild)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        cfg = await self._config(member.guild.id)
        if cfg is None:
            return
        await self._post(cfg, "leave", member, member.guild)

    @commands.Cog.listener()
    async def on_member_update(
        self, before: discord.Member, after: discord.Member
    ) -> None:
        if before.premium_since is None and after.premium_since is not None:
            cfg = await self._config(after.guild.id)
            if cfg is None:
                return
            await self._post(cfg, "boost", after, after.guild)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Welcome(bot))
