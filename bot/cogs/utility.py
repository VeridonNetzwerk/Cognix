"""Utility cog: info, ping, userinfo, serverinfo, roll, flip."""

from __future__ import annotations

import random
import time

import discord
import psutil
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select

from bot.utils.embeds import info_embed, ok_embed
from bot.utils.time_parser import humanize_seconds
from config.settings import get_settings


async def _load_embed_template(key: str):
    """Return EmbedTemplate row for ``key`` (server_id NULL = global) or None."""
    try:
        from database.models.embed_template import EmbedTemplate
        from database.session import db_session
    except Exception:  # noqa: BLE001
        return None
    try:
        async with db_session() as s:
            row = await s.scalar(
                select(EmbedTemplate).where(
                    EmbedTemplate.key == key,
                    EmbedTemplate.server_id.is_(None),
                    EmbedTemplate.enabled.is_(True),
                )
            )
            return row
    except Exception:  # noqa: BLE001
        return None


class Utility(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._proc = psutil.Process()

    @app_commands.command(name="ping", description="Show bot latency")
    async def ping(self, interaction: discord.Interaction) -> None:
        latency = round(self.bot.latency * 1000, 1)
        await interaction.response.send_message(
            embed=ok_embed("Pong", f"Latency: **{latency} ms**"), ephemeral=True
        )

    @app_commands.command(name="info", description="Bot information")
    async def info(self, interaction: discord.Interaction) -> None:
        from datetime import datetime, timezone

        bot = self.bot
        start = getattr(bot, "start_time", time.time())
        uptime = humanize_seconds(int(time.time() - start))
        latency_ms = round(bot.latency * 1000, 1) if bot.latency else 0
        guild_count = len(bot.guilds)
        total_users = sum(g.member_count or 0 for g in bot.guilds)
        online_users = sum(
            1 for g in bot.guilds for m in g.members
            if m.status != discord.Status.offline
        )
        connected_since = discord.utils.format_dt(
            datetime.fromtimestamp(start, tz=timezone.utc), "R"
        )

        status_dot = "🟢" if bot.is_ready() else "🔴"
        intents = bot.intents
        member_intent = "✅" if intents.members else "❌"
        dev_mode = "✅" if get_settings().is_dev else "❌"
        version = "v0.1.0"
        website = get_settings().app_base_url.rstrip("/") or "—"

        custom = await _load_embed_template("info")

        title = (custom and custom.title) or f"{bot.user.name if bot.user else 'CogniX'} Information"
        description = (custom and custom.description) or (
            f"{status_dot} **Bot Status:** Online\n"
            f"_(0 errors / 0 warnings)_"
        )
        color = (custom and custom.color) or 0x60A5FA

        embed = discord.Embed(title=title, description=description, color=color)
        if bot.user and bot.user.display_avatar:
            embed.set_thumbnail(url=bot.user.display_avatar.url)

        embed.add_field(name="Total Users", value=f"`{total_users}`", inline=True)
        embed.add_field(name="Total Servers", value=f"`{guild_count}`", inline=True)
        embed.add_field(name="Connected Since", value=connected_since, inline=True)

        embed.add_field(name="Online Users", value=f"`{online_users}`", inline=True)
        embed.add_field(name="Uptime", value=f"`{uptime}`", inline=True)
        embed.add_field(name="Ping", value=f"`{latency_ms} ms`", inline=True)

        embed.add_field(name="Member Intent", value=member_intent, inline=True)
        embed.add_field(name="Up to Date?", value="✅", inline=True)
        embed.add_field(name="Developer Mode", value=dev_mode, inline=True)

        embed.add_field(name="Bot Website", value=f"[Open Dashboard]({website})", inline=True)
        embed.add_field(name="Bot Version", value=f"`{version}`", inline=True)
        embed.add_field(
            name="Credits",
            value="Made by 食べ物 · [GitHub](https://github.com/VeridonNetzwerk)",
            inline=True,
        )

        # Apply extra fields from custom template, if any
        if custom and custom.fields:
            for f in custom.fields:
                embed.add_field(
                    name=f.get("name", "—"),
                    value=f.get("value", "—"),
                    inline=bool(f.get("inline", True)),
                )

        footer_text = (custom and custom.footer_text) or "Powered by Cognix · Made by 食べ物"
        embed.set_footer(text=footer_text)

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="userinfo", description="Show user details")
    async def userinfo(
        self, interaction: discord.Interaction, user: discord.Member | None = None
    ) -> None:
        from datetime import datetime, timezone

        from sqlalchemy import func

        from database.models.moderation import ModerationAction
        from database.models.stats import StatEvent, StatEventType
        from database.session import db_session

        target = user or interaction.user
        guild = interaction.guild

        def _ago(dt) -> str:
            if not dt:
                return "—"
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            delta = datetime.now(tz=timezone.utc) - dt
            seconds = max(0, int(delta.total_seconds()))
            years, rem = divmod(seconds, 365 * 24 * 3600)
            months, rem = divmod(rem, 30 * 24 * 3600)
            days, _ = divmod(rem, 24 * 3600)
            if years:
                rel = f"{years} year{'s' if years != 1 else ''} ago"
            elif months:
                rel = f"{months} month{'s' if months != 1 else ''} ago"
            elif days:
                rel = f"{days} day{'s' if days != 1 else ''} ago"
            else:
                hours = seconds // 3600
                rel = f"{hours} hour{'s' if hours != 1 else ''} ago"
            return f"{rel} ({dt.strftime('%d.%m.%Y')})"

        e = info_embed(f"User – {target}")
        e.set_thumbnail(url=target.display_avatar.url)

        e.add_field(name="ID", value=str(target.id), inline=True)
        e.add_field(name="Display Name",
                    value=getattr(target, "display_name", target.name), inline=True)
        e.add_field(name="Is Bot", value="Yes" if target.bot else "No", inline=True)

        e.add_field(name="Created", value=_ago(target.created_at), inline=False)

        if isinstance(target, discord.Member):
            status_map = {
                discord.Status.online: "🟢 Online",
                discord.Status.idle: "🟡 Idle",
                discord.Status.dnd: "🔴 Do Not Disturb",
                discord.Status.offline: "⚫ Offline",
            }
            e.add_field(name="Status",
                        value=status_map.get(target.status, str(target.status)),
                        inline=True)
            e.add_field(name="Boosting",
                        value=_ago(target.premium_since) if target.premium_since else "No",
                        inline=True)
            voice_channel = target.voice.channel.mention if target.voice and target.voice.channel else "—"
            e.add_field(name="Voice channel", value=voice_channel, inline=True)

            if target.joined_at:
                e.add_field(name="Joined", value=_ago(target.joined_at), inline=False)

                if guild is not None:
                    members_with_join = [m for m in guild.members if m.joined_at is not None]
                    members_with_join.sort(key=lambda m: m.joined_at)
                    try:
                        position = members_with_join.index(target) + 1
                        e.add_field(name="Join position",
                                    value=f"#{position} of {len(members_with_join)}",
                                    inline=True)
                    except ValueError:
                        pass

            roles = [r.mention for r in target.roles[1:]]
            if roles:
                e.add_field(name=f"Roles ({len(roles)})",
                            value=" ".join(roles[:25]), inline=False)

        # Database lookups: messages, punishments
        message_count = 0
        punishments: list[ModerationAction] = []
        try:
            async with db_session() as s:
                if guild is not None:
                    message_count = await s.scalar(
                        select(func.count(StatEvent.id)).where(
                            StatEvent.server_id == guild.id,
                            StatEvent.user_id == target.id,
                            StatEvent.event_type == StatEventType.MESSAGE,
                        )
                    ) or 0
                    punishments = list((await s.scalars(
                        select(ModerationAction)
                        .where(
                            ModerationAction.server_id == guild.id,
                            ModerationAction.target_id == target.id,
                        )
                        .order_by(ModerationAction.created_at.desc())
                        .limit(5)
                    )).all())
        except Exception:  # noqa: BLE001
            pass

        e.add_field(name="Total messages", value=f"`{message_count}`", inline=True)

        if punishments:
            lines = []
            for p in punishments:
                ts = p.created_at.strftime('%d.%m.%Y') if p.created_at else "—"
                reason = (p.reason or "—")[:60]
                lines.append(f"• `{p.action_type.value}` · {ts} · {reason}")
            e.add_field(name="Latest punishments",
                        value="\n".join(lines), inline=False)
        else:
            e.add_field(name="Latest punishments", value="None", inline=False)

        e.set_footer(text="Powered by Cognix · Made by 食べ物")
        await interaction.response.send_message(embed=e, ephemeral=True)

    @app_commands.command(name="serverinfo", description="Show server details")
    async def serverinfo(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message("Guild only", ephemeral=True)
            return
        e = info_embed(f"Server – {guild.name}")
        if guild.icon:
            e.set_thumbnail(url=guild.icon.url)
        e.add_field(name="ID", value=str(guild.id))
        e.add_field(name="Owner", value=f"<@{guild.owner_id}>")
        e.add_field(name="Members", value=str(guild.member_count))
        e.add_field(name="Channels", value=str(len(guild.channels)))
        e.add_field(name="Roles", value=str(len(guild.roles)))
        e.add_field(name="Created", value=discord.utils.format_dt(guild.created_at, "F"))
        await interaction.response.send_message(embed=e, ephemeral=True)

    @app_commands.command(name="roll", description="Roll a number from 1..N (default 100)")
    async def roll(
        self, interaction: discord.Interaction, max_value: app_commands.Range[int, 2, 1_000_000] = 100
    ) -> None:
        n = random.randint(1, max_value)  # noqa: S311
        await interaction.response.send_message(f"🎲 **{n}** (1..{max_value})")

    @app_commands.command(name="flip", description="Flip a coin")
    async def flip(self, interaction: discord.Interaction) -> None:
        result = random.choice(("Heads", "Tails"))  # noqa: S311
        await interaction.response.send_message(f"🪙 **{result}**")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Utility(bot))
