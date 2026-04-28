"""CogniX Discord bot client."""

from __future__ import annotations

import asyncio
import time
from typing import Any

import discord
import psutil
from discord.ext import commands

from config.crypto import decrypt_secret
from config.logging import get_logger
from config.settings import get_settings
from bot.ipc.consumer import IpcConsumer

log = get_logger("bot.client")

INITIAL_COGS = (
    "bot.cogs.moderation",
    "bot.cogs.utility",
    "bot.cogs.tickets",
    "bot.cogs.stats",
    "bot.cogs.backups",
    "bot.cogs.music",
    "bot.cogs.activity_log",
    "bot.cogs.giveaway",
    "bot.cogs.welcome",
)


class CogniXBot(commands.Bot):
    """The main bot class."""

    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True
        intents.guilds = True
        super().__init__(
            command_prefix=commands.when_mentioned_or("!"),
            intents=intents,
            help_command=None,
            allowed_mentions=discord.AllowedMentions(everyone=False, roles=False),
        )
        self.start_time: float = 0.0
        self.ipc = IpcConsumer()
        self._proc = psutil.Process()

    # ---- lifecycle ----
    async def setup_hook(self) -> None:
        # Per-server cog gate: silently rejects app-commands for cogs disabled
        # on the invoking guild via ServerCogState.
        async def _cog_gate(interaction: discord.Interaction) -> bool:
            cmd = interaction.command
            if cmd is None or interaction.guild is None:
                return True
            cog = getattr(cmd, "binding", None) or getattr(cmd, "cog", None)
            cog_name = getattr(cog, "qualified_name", None) or getattr(cog, "__cog_name__", None)
            if not cog_name:
                return True
            from bot.runtime import is_cog_enabled_for_server

            short = cog_name.lower()
            ok = await is_cog_enabled_for_server(interaction.guild.id, short)
            if not ok:
                try:
                    await interaction.response.send_message(
                        "This module is disabled on this server.", ephemeral=True
                    )
                except Exception:  # noqa: BLE001
                    pass
            return ok

        self.tree.interaction_check = _cog_gate  # type: ignore[assignment]

        for ext in INITIAL_COGS:
            try:
                await self.load_extension(ext)
                log.info("cog_loaded", cog=ext)
            except Exception as exc:  # noqa: BLE001
                log.warning("cog_load_failed", cog=ext, error=str(exc))

        # Slash command sync (dev: per-guild faster; prod: global once)
        try:
            synced = await self.tree.sync()
            log.info("slash_synced", count=len(synced))
        except Exception as exc:  # noqa: BLE001
            log.warning("slash_sync_failed", error=str(exc))

        # IPC
        await self._register_ipc()
        await self.ipc.start()

    async def on_ready(self) -> None:
        if self.start_time == 0.0:
            self.start_time = time.time()
        log.info(
            "bot_ready",
            user=str(self.user),
            guilds=len(self.guilds),
        )
        # Backfill any guild that joined while the bot was offline so FK
        # constraints (stat_events.server_id, tickets.server_id, ...) hold.
        try:
            await self._sync_all_guilds()
        except Exception as exc:  # noqa: BLE001
            log.warning("guild_sync_failed", error=str(exc))

    async def _sync_all_guilds(self) -> None:
        from database import db_session
        from database.models.server import Server
        from database.models.server_config import ServerConfig

        async with db_session() as s:
            for guild in self.guilds:
                existing = await s.get(Server, guild.id)
                if existing is None:
                    s.add(Server(
                        id=guild.id,
                        name=guild.name,
                        member_count=guild.member_count or 0,
                    ))
                    s.add(ServerConfig(server_id=guild.id))
                else:
                    existing.deleted_at = None
                    existing.is_active = True
                    existing.name = guild.name
                    if guild.member_count:
                        existing.member_count = guild.member_count

    async def on_guild_join(self, guild: discord.Guild) -> None:
        from database import db_session
        from database.models.server import Server
        from database.models.server_config import ServerConfig

        async with db_session() as s:
            existing = await s.get(Server, guild.id)
            if existing is None:
                s.add(Server(id=guild.id, name=guild.name, member_count=guild.member_count or 0))
                s.add(ServerConfig(server_id=guild.id))
            else:
                existing.deleted_at = None
                existing.is_active = True
                existing.name = guild.name

    # ---- IPC handlers ----
    async def _register_ipc(self) -> None:
        self.ipc.register("status", self._ipc_status)
        self.ipc.register("restart", self._ipc_restart)
        self.ipc.register("presence", self._ipc_presence)
        self.ipc.register("cog.list", self._ipc_cog_list)
        self.ipc.register("cog.load", self._ipc_cog_load)
        self.ipc.register("cog.unload", self._ipc_cog_unload)
        self.ipc.register("cog.reload", self._ipc_cog_reload)

        # Cogs register their own IPC handlers in their setup() if needed
        # via self.ipc.register inside the cog. (See moderation cog.)

    async def _ipc_status(self, _: dict[str, Any]) -> dict[str, Any]:
        mem = self._proc.memory_info().rss / (1024 * 1024)
        return {
            "online": self.is_ready(),
            "latency_ms": round(self.latency * 1000, 2) if self.latency else None,
            "guild_count": len(self.guilds),
            "user_count": len({m.id for g in self.guilds for m in g.members}) or sum(g.member_count or 0 for g in self.guilds),
            "uptime_seconds": time.time() - (self.start_time or time.time()),
            "memory_mb": round(mem, 2),
            "version": "0.1.0",
        }

    async def _ipc_restart(self, _: dict[str, Any]) -> dict[str, Any]:
        asyncio.create_task(self._delayed_close())
        return {"ok": True}

    async def _delayed_close(self) -> None:
        await asyncio.sleep(0.5)
        await self.close()

    async def _ipc_presence(self, payload: dict[str, Any]) -> dict[str, Any]:
        text = payload.get("text", "")
        type_ = payload.get("type", "playing")
        type_map = {
            "playing": discord.ActivityType.playing,
            "watching": discord.ActivityType.watching,
            "listening": discord.ActivityType.listening,
            "competing": discord.ActivityType.competing,
        }
        activity = discord.Activity(type=type_map.get(type_, discord.ActivityType.playing), name=text)
        await self.change_presence(activity=activity)
        return {"ok": True}

    async def _ipc_cog_list(self, _: dict[str, Any]) -> dict[str, Any]:
        return {"loaded": list(self.extensions.keys())}

    async def _cog_action(self, name: str, action: str) -> dict[str, Any]:
        ext = name if name.startswith("bot.cogs.") else f"bot.cogs.{name}"
        try:
            if action == "load":
                await self.load_extension(ext)
            elif action == "unload":
                await self.unload_extension(ext)
            elif action == "reload":
                await self.reload_extension(ext)
            else:
                return {"error": "unknown action"}
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(str(exc)) from exc
        return {"ok": True}

    async def _ipc_cog_load(self, p: dict[str, Any]) -> dict[str, Any]:
        return await self._cog_action(p["name"], "load")

    async def _ipc_cog_unload(self, p: dict[str, Any]) -> dict[str, Any]:
        return await self._cog_action(p["name"], "unload")

    async def _ipc_cog_reload(self, p: dict[str, Any]) -> dict[str, Any]:
        return await self._cog_action(p["name"], "reload")


async def run_bot() -> None:
    """Resolve token (DB-encrypted or env) and run the bot."""
    settings = get_settings()
    token = settings.discord_bot_token
    if not token:
        # Fetch from DB
        from sqlalchemy import select
        from database import db_session
        from database.models.system_config import SystemConfig

        async with db_session() as s:
            cfg = await s.scalar(select(SystemConfig).where(SystemConfig.id == 1))
            if cfg and cfg.bot_token_encrypted:
                token = decrypt_secret(cfg.bot_token_encrypted, aad=b"bot_token")

    if not token:
        log.warning("bot_no_token_idle")
        # Idle loop: API may finish setup; we let main.py restart us
        while True:
            await asyncio.sleep(30)

    bot = CogniXBot()
    from bot.runtime import clear_bot, set_bot

    set_bot(bot)
    try:
        await bot.start(token)
    except discord.LoginFailure:
        log.error("bot_login_failed")
        raise
    finally:
        clear_bot()
        await bot.ipc.stop()
        if not bot.is_closed():
            await bot.close()
