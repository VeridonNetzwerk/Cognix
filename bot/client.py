"""CogniX Discord bot client."""

from __future__ import annotations

import asyncio
import time
from typing import Any

import discord
import psutil
from discord.ext import commands

from bot.config.crypto import decrypt_secret
from bot.config.logging import get_logger
from bot.config.settings import get_settings
from bot.ipc import IpcConsumer

log = get_logger("bot.client")


_ACTIVITY_TYPE_MAP = {
    "playing": discord.ActivityType.playing,
    "watching": discord.ActivityType.watching,
    "listening": discord.ActivityType.listening,
    "streaming": discord.ActivityType.streaming,
    "competing": discord.ActivityType.competing,
}


def _build_activity(payload: dict[str, Any]) -> discord.Activity:
    """Build a discord.Activity from a presence payload dict."""
    return discord.Activity(
        type=_ACTIVITY_TYPE_MAP.get(payload.get("type", "playing"), discord.ActivityType.playing),
        name=payload.get("text", ""),
    )


async def _fetch_token() -> str | None:
    """Fetch bot token from env or DB."""
    token = get_settings().discord_bot_token
    if token:
        return token
    from sqlalchemy import select
    from bot.database import db_session
    from bot.database.models.system.system_config import SystemConfig

    async with db_session() as s:
        cfg = await s.scalar(select(SystemConfig).where(SystemConfig.id == 1))
        if cfg and cfg.bot_token_encrypted:
            return decrypt_secret(cfg.bot_token_encrypted, aad=b"bot_token")
    return None


class CogniXBot(commands.Bot):
    """The main bot class."""

    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True
        intents.guilds = True
        # FEAT #9: turn off heavy intents we don't use
        intents.typing = False
        intents.presences = False
        # Needed for invite tracker (manage_guild perm grants invites events)
        intents.invites = True
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
        # Per-server cog gate: rejects app-commands for cogs that are either
        # not loaded globally OR disabled on the invoking guild.
        async def _cog_gate(interaction: discord.Interaction) -> bool:
            cmd = interaction.command
            if cmd is None or interaction.guild is None:
                return True
            cog = getattr(cmd, "binding", None) or getattr(cmd, "cog", None)
            cog_name = getattr(cog, "qualified_name", None) or getattr(cog, "__cog_name__", None)
            if not cog_name:
                return True

            # Check 1: Is the cog actually loaded? Discord caches global
            # slash commands for up to 1h, so unloaded cogs' commands may
            # still be visible to users. Reject the interaction server-side.
            cog_module = getattr(cog, "__module__", None)
            from bot.cogs.registry import get_cog_info

            info = get_cog_info(cog_name)
            if (cog_module and cog_module not in self.extensions) or (info and info["module"] not in self.extensions):
                try:
                    await interaction.response.send_message(
                        "This module is not loaded. Ask an admin to load it via the dashboard.",
                        ephemeral=True,
                    )
                except Exception:  # noqa: BLE001
                    pass
                return False

            # Check 2: Per-server enable/disable
            from bot.runtime import is_cog_enabled_for_server

            ok = await is_cog_enabled_for_server(interaction.guild.id, cog_name.lower())
            if not ok:
                try:
                    await interaction.response.send_message(
                        "This module is disabled on this server.", ephemeral=True
                    )
                except Exception:  # noqa: BLE001
                    pass
            return ok

        self.tree.interaction_check = _cog_gate  # type: ignore[assignment]

        # NO auto-load of cogs — they are loaded lazily via admin commands,
        # web interface, or IPC. Use `registry.restore_loaded_cogs(bot)` to
        # restore previously-persisted load state after the bot is ready.

        # Slash command sync — use per-guild sync for instant propagation
        try:
            from bot.cogs.registry import _sync_commands_to_guilds
            await _sync_commands_to_guilds(self)
            log.info("slash_synced", count=len(self.tree.get_commands()))
        except Exception as exc:  # noqa: BLE001
            log.warning("slash_sync_failed", error=str(exc))

        # IPC
        await self._register_ipc()
        await self.ipc.start()

    async def on_ready(self) -> None:
        if self.start_time == 0.0:
            self.start_time = time.time()
        # Clear any previous error now that we're connected
        from bot.runtime import clear_bot_error
        clear_bot_error()
        # BUG #2: Pterodactyl egg detection string. The default "yolks:python"
        # egg matches "is online!" / "online!" / "Bot is online" patterns to
        # flip the server state from STARTING -> RUNNING.
        try:
            import sys as _sys
            user = self.user
            guilds_count = len(self.guilds)
            print(f"[Cognix] Bot is online! Logged in as {user} ({guilds_count} guilds).", flush=True)
            _sys.stdout.flush()
        except Exception:
            pass
        log.info(
            "bot_ready",
            user=str(self.user),
            guilds=len(self.guilds),
        )
        # Restore previously-persisted cog load state (lazy loading)
        try:
            from bot.cogs.registry import restore_loaded_cogs
            loaded = await restore_loaded_cogs(self)
            log.info("cogs_restored", count=loaded)
        except Exception as exc:  # noqa: BLE001
            log.warning("cog_restore_failed", error=str(exc))
        # Start idle audio player cleanup timer
        try:
            from bot.services.audio_player import start_cleanup_timer
            asyncio.create_task(start_cleanup_timer(self))
        except Exception as exc:  # noqa: BLE001
            log.warning("audio_cleanup_timer_failed", error=str(exc))
        # Start the live ping monitor (active Discord round-trip, every second,
        # non-overlapping). Guarded so it is only launched once per connection.
        if getattr(self, "_ping_task", None) is None or self._ping_task.done():
            try:
                from bot.runtime import run_ping_monitor
                self._ping_task = asyncio.create_task(
                    run_ping_monitor(self), name="ping-monitor"
                )
            except Exception as exc:  # noqa: BLE001
                log.warning("ping_monitor_failed", error=str(exc))
        # Backfill any guild that joined while the bot was offline so FK
        # constraints (stat_events.server_id, tickets.server_id, ...) hold.
        try:
            await self._sync_all_guilds()
        except Exception as exc:  # noqa: BLE001
            log.warning("guild_sync_failed", error=str(exc))

    async def _sync_all_guilds(self) -> None:
        from bot.database import db_session
        from bot.database.models.server.server import Server
        from bot.database.models.server.server_config import ServerConfig

        async with db_session() as s:
            for guild in self.guilds:
                existing = await s.get(Server, guild.id)
                if existing is None:
                    s.add(Server(
                        id=guild.id,
                        name=guild.name,
                        icon_hash=guild.icon.key if guild.icon else None,
                        member_count=guild.member_count or 0,
                    ))
                    s.add(ServerConfig(server_id=guild.id))
                else:
                    existing.deleted_at = None
                    existing.is_active = True
                    existing.name = guild.name
                    existing.icon_hash = guild.icon.key if guild.icon else None
                    if guild.member_count:
                        existing.member_count = guild.member_count

    async def on_guild_join(self, guild: discord.Guild) -> None:
        from bot.database import db_session
        from bot.database.models.server.server import Server
        from bot.database.models.server.server_config import ServerConfig

        async with db_session() as s:
            existing = await s.get(Server, guild.id)
            if existing is None:
                s.add(Server(id=guild.id, name=guild.name, icon_hash=guild.icon.key if guild.icon else None, member_count=guild.member_count or 0))
                s.add(ServerConfig(server_id=guild.id))
            else:
                existing.deleted_at = None
                existing.is_active = True
                existing.name = guild.name
                existing.icon_hash = guild.icon.key if guild.icon else None

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
            # Compute user count with fallback for efficiency
            "user_count": _compute_total_users(self),
            "uptime_seconds": time.time() - (self.start_time or time.time()),
            "memory_mb": round(mem, 2),
            "version": "0.1.0",
        }

    async def _ipc_restart(self, _: dict[str, Any]) -> dict[str, Any]:
        asyncio.create_task(self._delayed_close(), name="bot-restart")
        return {"ok": True}

    async def _delayed_close(self) -> None:
        await asyncio.sleep(0.5)
        await self.close()

    async def _ipc_presence(self, payload: dict[str, Any]) -> dict[str, Any]:
        await self.change_presence(activity=_build_activity(payload))
        return {"ok": True}

    async def _ipc_cog_list(self, _: dict[str, Any]) -> dict[str, Any]:
        return {"loaded": list(self.extensions.keys())}

    async def _ipc_cog_load(self, p: dict[str, Any]) -> dict[str, Any]:
        name = p.get("name")
        if not name:
            return {"error": "name required"}
        from bot.cogs.registry import load_cog
        return await load_cog(self, name)

    async def _ipc_cog_unload(self, p: dict[str, Any]) -> dict[str, Any]:
        name = p.get("name")
        if not name:
            return {"error": "name required"}
        from bot.cogs.registry import unload_cog
        return await unload_cog(self, name)

    async def _ipc_cog_reload(self, p: dict[str, Any]) -> dict[str, Any]:
        name = p.get("name")
        if not name:
            return {"error": "name required"}
        from bot.cogs.registry import reload_cog
        return await reload_cog(self, name)


async def run_bot() -> None:
    """Resolve token (DB-encrypted or env) and run the bot."""
    token = await _fetch_token()

    # Idle loop: API may finish setup; we let main.py restart us
    while not token:
        log.warning("bot_no_token_idle")
        await asyncio.sleep(30)
        token = await _fetch_token()

    from bot.runtime import clear_bot, clear_bot_error, set_bot, set_bot_error

    bot = CogniXBot()
    set_bot(bot)
    clear_bot_error()
    try:
        await bot.start(token)
    except discord.LoginFailure as exc:
        set_bot_error(f"Discord login failed: {exc}")
        log.error("bot_login_failed", error=str(exc))
        raise
    except discord.HTTPException as exc:
        set_bot_error(f"Discord HTTP error: {exc}")
        log.error("bot_http_error", error=str(exc))
        raise
    except Exception as exc:
        set_bot_error(f"Bot error: {exc}")
        log.error("bot_error", error=str(exc))
        raise
    finally:
        clear_bot()
        await bot.ipc.stop()
        if not bot.is_closed():
            await bot.close()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _compute_total_users(bot: CogniXBot) -> int:
    """Compute total users across all guilds with a fast path."""
    total = len({m.id for g in bot.guilds for m in g.members})
    if total > 0:
        return total
    return sum(g.member_count or 0 for g in bot.guilds)
