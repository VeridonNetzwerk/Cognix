"""CogniX – single entry point.

Starts the FastAPI server (uvicorn) and the Discord bot concurrently.
Runs Alembic migrations on first launch.

Usage:
    python main.py
"""

from __future__ import annotations

import asyncio
import signal
import sys
from pathlib import Path

import uvicorn
from alembic import command
from alembic.config import Config as AlembicConfig

from config.logging import configure_logging, get_logger
from config.settings import get_settings


ROOT = Path(__file__).resolve().parent


def _run_migrations_sync() -> None:
    settings = get_settings()
    settings.ensure_data_dirs()
    cfg = AlembicConfig(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "database" / "migrations"))
    # Do NOT pass sqlalchemy.url here — env.py reads it directly from settings
    # to bypass ConfigParser interpolation issues with percent-encoded passwords.
    command.upgrade(cfg, "head")


async def _run_migrations() -> None:
    # Alembic env executes asyncio.run() internally for async engines.
    # Running it in a worker thread avoids nested event-loop errors.
    await asyncio.to_thread(_run_migrations_sync)


async def _serve_api(stop: asyncio.Event) -> None:
    log = get_logger("main.api")
    settings = get_settings()
    log.info("api_binding", host=settings.app_host, port=settings.app_port)
    config = uvicorn.Config(
        "web.app:app",
        host=settings.app_host,
        port=settings.app_port,
        log_level=settings.log_level.lower(),
        access_log=False,
        loop="asyncio",
    )
    server = uvicorn.Server(config)

    async def _run() -> None:
        try:
            await server.serve()
        except Exception:  # noqa: BLE001
            log.exception("api_server_serve_failed")
            raise

    task = asyncio.create_task(_run(), name="api-server")
    await stop.wait()
    server.should_exit = True
    await task


async def _serve_bot(stop: asyncio.Event) -> None:
    log = get_logger("main.bot")
    while not stop.is_set():
        try:
            from bot.client import run_bot
            from bot.runtime import is_bot_paused, wait_for_resume

            if is_bot_paused():
                # Block until start is requested or shutdown — no busy-poll.
                resumed = await wait_for_resume(timeout=30.0)
                if stop.is_set():
                    break
                if not resumed and is_bot_paused():
                    continue
                # fall through and (re)start the bot
                continue

            await run_bot()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            log.warning("bot_crashed_restarting", error=str(exc))
        # backoff
        try:
            await asyncio.wait_for(stop.wait(), timeout=2)
        except asyncio.TimeoutError:
            continue


async def _main() -> int:
    configure_logging()
    settings = get_settings()
    log = get_logger("main")
    log.info(
        "cognix_starting",
        env=settings.app_env,
        db=settings.db_kind,
        redis_enabled=settings.redis_enabled,
        frontend_enabled=settings.serve_frontend,
    )
    try:
        await _run_migrations()
    except Exception as exc:  # noqa: BLE001
        log.error("migrations_failed", error=str(exc))
        return 1

    stop = asyncio.Event()

    def _stop(*_: object) -> None:
        stop.set()

    loop = asyncio.get_running_loop()
    if sys.platform != "win32":
        loop.add_signal_handler(signal.SIGINT, _stop)
        loop.add_signal_handler(signal.SIGTERM, _stop)

    api = asyncio.create_task(_serve_api(stop), name="api")
    bot = asyncio.create_task(_serve_bot(stop), name="bot")

    # Propagate silent crashes from the API task immediately.
    def _api_done(t: asyncio.Task) -> None:
        if not t.cancelled() and t.exception() is not None:
            log.error("api_task_crashed", error=str(t.exception()))
            stop.set()

    api.add_done_callback(_api_done)

    try:
        await stop.wait()
    except (KeyboardInterrupt, asyncio.CancelledError):
        stop.set()

    for t in (api, bot):
        t.cancel()
    await asyncio.gather(api, bot, return_exceptions=True)
    log.info("cognix_stopped")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(_main()))
    except KeyboardInterrupt:
        raise SystemExit(0) from None
