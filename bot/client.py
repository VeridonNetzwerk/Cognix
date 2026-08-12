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
            if cog_module and cog_module not in self.extensions:
                try:
                    await interaction.response.send_message(
                        "This module is not loaded. Ask an admin to load it via the dashboard.",
                        ephemeral=True,
                    )
                except Exception:  # noqa: BLE001
                    pass
                return False

            # Also check via cog name → module mapping from registry
            from bot.cogs.registry import get_cog_info

            info = get_cog_info(cog_name)
            if info and info["module"] not in self.extensions:
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
        from bot.database import db_session
        from bot.database.models.server.server import Server
        from bot.database.models.server.server_config import ServerConfig

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

        # Marketplace IPC handlers (forward to loaded marketplace cog)
        self.ipc.register("marketplace.install", self._ipc_marketplace_install)
        self.ipc.register("marketplace.uninstall", self._ipc_marketplace_uninstall)
        self.ipc.register("marketplace.list", self._ipc_marketplace_list)

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
        text = payload.get("text", "")
        type_ = payload.get("type", "playing")
        type_map = {
            "playing": discord.ActivityType.playing,
            "watching": discord.ActivityType.watching,
            "listening": discord.ActivityType.listening,
            "competing": discord.ActivityType.competing,
        }
        activity = discord.Activity(
            type=type_map.get(type_, discord.ActivityType.playing),
            name=text,
        )
        await self.change_presence(activity=activity)
        return {"ok": True}

    async def _ipc_cog_list(self, _: dict[str, Any]) -> dict[str, Any]:
        return {"loaded": list(self.extensions.keys())}

    async def _cog_action(self, name: str, action: str) -> dict[str, Any]:
        from bot.cogs.registry import get_cog_info
        if name.startswith("bot."):
            ext = name
        else:
            info = get_cog_info(name)
            ext = info["module"] if info else f"bot.cogs.{name}"
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
        name = p.get("name")
        if not name:
            return {"error": "name required"}
        result = await self._cog_action(name, "load")
        if result.get("ok"):
            # Sync per-guild so new commands appear instantly
            try:
                from bot.cogs.registry import _sync_commands_to_guilds
                await _sync_commands_to_guilds(self)
            except Exception:  # noqa: BLE001
                pass
        return result

    async def _ipc_cog_unload(self, p: dict[str, Any]) -> dict[str, Any]:
        name = p.get("name")
        if not name:
            return {"error": "name required"}
        result = await self._cog_action(name, "unload")
        if result.get("ok"):
            # Sync per-guild so removed commands disappear instantly
            try:
                from bot.cogs.registry import _sync_commands_to_guilds
                await _sync_commands_to_guilds(self)
            except Exception:  # noqa: BLE001
                pass
        return result

    async def _ipc_cog_reload(self, p: dict[str, Any]) -> dict[str, Any]:
        name = p.get("name")
        if not name:
            return {"error": "name required"}
        result = await self._cog_action(name, "reload")
        if result.get("ok"):
            try:
                from bot.cogs.registry import _sync_commands_to_guilds
                await _sync_commands_to_guilds(self)
            except Exception:  # noqa: BLE001
                pass
        return result

    # -----------------------------------------------------------------------
    # Marketplace IPC handlers — forward to the loaded marketplace cog
    # -----------------------------------------------------------------------

    async def _ipc_marketplace_install(self, p: dict[str, Any]) -> dict[str, Any]:
        """Handle marketplace install requests from the web layer."""
        try:
            from bot.cogs.admin.marketplace import install_cog_from_source, save_package_metadata

            cog_or_url = p.get("cog_or_url", "")
            if not cog_or_url:
                return {"status": "error", "error": "cog_or_url required"}

            is_url = cog_or_url.startswith("http")
            if is_url:
                repo_url = cog_or_url
                cog_name = cog_or_url
            else:
                import httpx
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.get(
                        "https://raw.githubusercontent.com/VeridonNetzwerk/cognix-marketplace/main/registry.json"
                    )
                    resp.raise_for_status()
                    reg_data = resp.json()
                found = None
                if isinstance(reg_data, list):
                    for c in reg_data:
                        if c.get("name", "").lower() == cog_or_url.lower():
                            found = c
                            break
                elif isinstance(reg_data, dict) and "cogs" in reg_data:
                    for c in reg_data["cogs"]:
                        if c.get("name", "").lower() == cog_or_url.lower():
                            found = c
                            break
                if found is None:
                    return {"status": "error", "error": f"Unknown marketplace cog: {cog_or_url}"}
                repo_url = found.get("github_repo", "")
                cog_name = found.get("name", cog_or_url)

            result = await install_cog_from_source(self, repo_url, cog_name)
            if result.get("ok"):
                await save_package_metadata(
                    cog_name=cog_name,
                    display_name=cog_name,
                    description=f"Installed from {repo_url}",
                    github_repo=repo_url,
                    version=None,
                    dependencies=[],
                    category="Custom",
                    requires_admin=False,
                    author="Unknown",
                    installed=True,
                )
                try:
                    await self.tree.sync()
                except Exception:  # noqa: BLE001
                    pass
                return {"status": "ok", "payload": {"cog": cog_name}}
            return {"status": "error", "error": result.get("error", "unknown error")}
        except Exception as exc:  # noqa: BLE001
            return {"status": "error", "error": str(exc)}

    async def _ipc_marketplace_uninstall(self, p: dict[str, Any]) -> dict[str, Any]:
        """Handle marketplace uninstall requests from the web layer."""
        try:
            cog_name = p.get("cog_name", "")
            if not cog_name:
                return {"status": "error", "error": "cog_name required"}

            from bot.cogs.admin.marketplace import uninstall_cog

            result = await uninstall_cog(self, cog_name)
            if result.get("ok"):
                try:
                    await self.tree.sync()
                except Exception:  # noqa: BLE001
                    pass
                return {"status": "ok", "payload": {"cog": cog_name}}
            return {"status": "error", "error": result.get("error", "unknown error")}
        except Exception as exc:  # noqa: BLE001
            return {"status": "error", "error": str(exc)}

    async def _ipc_marketplace_list(self, _: dict[str, Any]) -> dict[str, Any]:
        """Return the curated marketplace registry."""
        try:
            import httpx
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    "https://raw.githubusercontent.com/VeridonNetzwerk/cognix-marketplace/main/registry.json"
                )
                resp.raise_for_status()
                data = resp.json()
                if isinstance(data, list):
                    return {"status": "ok", "payload": {"cogs": data}}
                if isinstance(data, dict) and "cogs" in data:
                    return {"status": "ok", "payload": {"cogs": data["cogs"]}}
        except Exception as exc:  # noqa: BLE001
            return {"status": "error", "error": str(exc)}
        return {"status": "error", "error": "invalid registry format"}


async def run_bot() -> None:
    """Resolve token (DB-encrypted or env) and run the bot."""
    settings = get_settings()
    token = settings.discord_bot_token
    if not token:
        # Fetch from DB
        from sqlalchemy import select
        from bot.database import db_session
        from bot.database.models.system.system_config import SystemConfig

        async with db_session() as s:
            cfg = await s.scalar(select(SystemConfig).where(SystemConfig.id == 1))
            if cfg and cfg.bot_token_encrypted:
                token = decrypt_secret(cfg.bot_token_encrypted, aad=b"bot_token")

    # Idle loop: API may finish setup; we let main.py restart us
    while not token:
        log.warning("bot_no_token_idle")
        await asyncio.sleep(30)
        # Re-check both env and DB in case bot_token was set at runtime
        token = get_settings().discord_bot_token
        if not token:
            from sqlalchemy import select as sa_select
            from bot.database import db_session as _db
            from bot.database.models.system.system_config import SystemConfig as _Cfg

            async with _db() as s:
                cfg = await s.scalar(sa_select(_Cfg).where(_Cfg.id == 1))
                if cfg and cfg.bot_token_encrypted:
                    token = decrypt_secret(cfg.bot_token_encrypted, aad=b"bot_token")

    from bot.runtime import clear_bot, set_bot

    bot = CogniXBot()
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _compute_total_users(bot: CogniXBot) -> int:
    """Compute total users across all guilds with a fast path."""
    total = len({m.id for g in bot.guilds for m in g.members})
    if total > 0:
        return total
    return sum(g.member_count or 0 for g in bot.guilds)
