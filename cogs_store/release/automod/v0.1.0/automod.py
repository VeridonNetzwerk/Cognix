"""Auto-Moderation cog: spam, link, mention, and word filter protection.

Per-server configuration is stored in ``ServerConfig.extras["automod"]``.
All checks are listener-based and do not add slash commands beyond
``/automod-config`` for configuration.
"""

from __future__ import annotations

COG_INFO = {
    "name": "Auto-Moderation",
    "description": "Automatic spam, link, mention, and word filter protection",
    "category": "Moderation",
    "requires_admin": True,
    "version": "0.1.0",
}

import re
import time
from collections import defaultdict, deque
from datetime import UTC, datetime, timedelta

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select

from bot.config.logging import get_logger
from bot.database import db_session
from bot.database.models.server.server_config import ServerConfig
from bot.utils.embeds import err_embed, ok_embed
from bot.utils.time_parser import humanize_seconds, parse_duration

log = get_logger("bot.cogs.automod")

_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
_DEFAULT_CFG: dict = {
    "spam_threshold": 5,
    "spam_window_seconds": 5,
    "spam_mute_seconds": 600,
    "block_links": False,
    "link_whitelist": [],
    "max_mentions": 5,
    "mention_mute_seconds": 600,
    "blocked_words": [],
    "word_mute_seconds": 600,
    "exempt_role_ids": [],
}


def _merge_cfg(stored: dict | None) -> dict:
    cfg = dict(_DEFAULT_CFG)
    if stored:
        cfg.update(stored)
    return cfg


class AutoMod(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        # guild_id -> user_id -> deque[timestamp]
        self._spam_tracker: dict[int, dict[int, deque[float]]] = defaultdict(lambda: defaultdict(deque))

    async def _get_cfg(self, guild_id: int) -> dict:
        async with db_session() as s:
            cfg = await s.scalar(
                select(ServerConfig).where(ServerConfig.server_id == guild_id)
            )
            return _merge_cfg((cfg.extras if cfg else {}).get("automod"))

    def _is_exempt(self, member: discord.Member, cfg: dict) -> bool:
        if member.guild_permissions.manage_messages:
            return True
        exempt_ids = set(cfg.get("exempt_role_ids", []))
        return any(r.id in exempt_ids for r in member.roles)

    async def _punish(
        self,
        member: discord.Member,
        reason: str,
        seconds: int,
    ) -> bool:
        try:
            until = datetime.now(UTC) + timedelta(seconds=min(seconds, 28 * 86400))
            await member.timeout(until, reason=reason)
            return True
        except discord.HTTPException:
            log.warning("automod_punish_failed", member_id=member.id, exc_info=True)
            return False

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.guild is None or message.author.bot:
            return
        member = message.author
        if not isinstance(member, discord.Member):
            return

        cfg = await self._get_cfg(message.guild.id)
        if self._is_exempt(member, cfg):
            return

        # --- Spam check ---
        now = time.monotonic()
        window = cfg.get("spam_window_seconds", 5)
        threshold = cfg.get("spam_threshold", 5)
        tracker = self._spam_tracker[message.guild.id][member.id]
        tracker.append(now)
        while tracker and (now - tracker[0]) > window:
            tracker.popleft()
        if len(tracker) >= threshold:
            tracker.clear()
            muted = await self._punish(
                member, f"Auto-mod: spam ({threshold} msgs in {window}s)", cfg.get("spam_mute_seconds", 600)
            )
            if muted:
                try:
                    await message.delete()
                except discord.HTTPException:
                    pass
                return

        # --- Link check ---
        if cfg.get("block_links", False):
            urls = _URL_RE.findall(message.content or "")
            whitelist = cfg.get("link_whitelist", [])
            blocked = [u for u in urls if not any(w in u for w in whitelist)]
            if blocked:
                muted = await self._punish(
                    member, "Auto-mod: blocked link", cfg.get("spam_mute_seconds", 600)
                )
                if muted:
                    try:
                        await message.delete()
                    except discord.HTTPException:
                        pass
                    return

        # --- Mention check ---
        max_mentions = cfg.get("max_mentions", 5)
        if max_mentions and len(message.mentions) > max_mentions:
            muted = await self._punish(
                member,
                f"Auto-mod: too many mentions ({len(message.mentions)})",
                cfg.get("mention_mute_seconds", 600),
            )
            if muted:
                try:
                    await message.delete()
                except discord.HTTPException:
                    pass
                return

        # --- Word filter ---
        blocked_words = cfg.get("blocked_words", [])
        if blocked_words:
            content_lower = (message.content or "").lower()
            for word in blocked_words:
                if word.lower() in content_lower:
                    muted = await self._punish(
                        member,
                        f"Auto-mod: blocked word '{word}'",
                        cfg.get("word_mute_seconds", 600),
                    )
                    if muted:
                        try:
                            await message.delete()
                        except discord.HTTPException:
                            pass
                    return

    # ---------- config commands ----------

    group = app_commands.Group(name="automod", description="Auto-moderation configuration")

    @group.command(name="config", description="View current auto-mod settings")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def view_config(self, interaction: discord.Interaction) -> None:
        if interaction.guild_id is None:
            await interaction.response.send_message("Guild only", ephemeral=True)
            return
        cfg = await self._get_cfg(interaction.guild_id)
        lines = [
            f"Spam threshold: **{cfg['spam_threshold']}** msgs / {cfg['spam_window_seconds']}s → mute {humanize_seconds(cfg['spam_mute_seconds'])}",
            f"Block links: **{'on' if cfg['block_links'] else 'off'}** (whitelist: {len(cfg.get('link_whitelist', []))})",
            f"Max mentions: **{cfg['max_mentions']}** → mute {humanize_seconds(cfg['mention_mute_seconds'])}",
            f"Blocked words: **{len(cfg.get('blocked_words', []))}** → mute {humanize_seconds(cfg['word_mute_seconds'])}",
            f"Exempt roles: {len(cfg.get('exempt_role_ids', []))}",
        ]
        await interaction.response.send_message(
            embed=ok_embed("Auto-Mod Config", "\n".join(lines)), ephemeral=True
        )

    @group.command(name="spam", description="Configure spam detection")
    @app_commands.describe(
        threshold="Messages in window before mute (0 = disable)",
        window="Time window in seconds (default 5)",
        mute_duration="Mute duration, e.g. 10m, 1h (default 10m)",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def set_spam(
        self,
        interaction: discord.Interaction,
        threshold: app_commands.Range[int, 0, 50] = 5,
        window: app_commands.Range[int, 1, 60] = 5,
        mute_duration: str = "10m",
    ) -> None:
        await self._update_cfg(interaction, {
            "spam_threshold": threshold,
            "spam_window_seconds": window,
            "spam_mute_seconds": parse_duration(mute_duration) or 600,
        })

    @group.command(name="links", description="Toggle link blocking")
    @app_commands.describe(
        enabled="True to block links, False to allow",
        whitelist="Comma-separated domains to whitelist (e.g. discord.gg,youtube.com)",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def set_links(
        self,
        interaction: discord.Interaction,
        enabled: bool,
        whitelist: str = "",
    ) -> None:
        wl = [w.strip() for w in whitelist.split(",") if w.strip()] if whitelist else []
        await self._update_cfg(interaction, {
            "block_links": enabled,
            "link_whitelist": wl,
        })

    @group.command(name="mentions", description="Configure max mentions per message")
    @app_commands.describe(
        max_mentions="Max mentions allowed (0 = disable)",
        mute_duration="Mute duration, e.g. 10m, 1h (default 10m)",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def set_mentions(
        self,
        interaction: discord.Interaction,
        max_mentions: app_commands.Range[int, 0, 50] = 5,
        mute_duration: str = "10m",
    ) -> None:
        await self._update_cfg(interaction, {
            "max_mentions": max_mentions,
            "mention_mute_seconds": parse_duration(mute_duration) or 600,
        })

    @group.command(name="words", description="Configure blocked words")
    @app_commands.describe(
        words="Comma-separated words to block (empty to clear)",
        mute_duration="Mute duration, e.g. 10m, 1h (default 10m)",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def set_words(
        self,
        interaction: discord.Interaction,
        words: str = "",
        mute_duration: str = "10m",
    ) -> None:
        word_list = [w.strip() for w in words.split(",") if w.strip()] if words else []
        await self._update_cfg(interaction, {
            "blocked_words": word_list,
            "word_mute_seconds": parse_duration(mute_duration) or 600,
        })

    @group.command(name="exempt", description="Set roles exempt from auto-mod")
    @app_commands.describe(role_ids="Comma-separated role IDs to exempt")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def set_exempt(
        self,
        interaction: discord.Interaction,
        role_ids: str = "",
    ) -> None:
        ids: list[int] = []
        for r in role_ids.split(","):
            r = r.strip()
            if r.isdigit():
                ids.append(int(r))
        await self._update_cfg(interaction, {"exempt_role_ids": ids})

    async def _update_cfg(self, interaction: discord.Interaction, updates: dict) -> None:
        if interaction.guild_id is None:
            await interaction.response.send_message("Guild only", ephemeral=True)
            return
        async with db_session() as s:
            cfg = await s.scalar(
                select(ServerConfig).where(ServerConfig.server_id == interaction.guild_id)
            )
            if cfg is None:
                cfg = ServerConfig(server_id=interaction.guild_id)
                s.add(cfg)
            extras = dict(cfg.extras or {})
            current = _merge_cfg(extras.get("automod"))
            current.update(updates)
            extras["automod"] = current
            cfg.extras = extras
        await interaction.response.send_message(
            embed=ok_embed("Auto-Mod updated", "Configuration saved."), ephemeral=True
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AutoMod(bot))
