"""Bot control routes (status, restart, presence)."""

from __future__ import annotations

import os
import time

import psutil

from fastapi import APIRouter, Depends, HTTPException, status

from bot.client import _build_activity
from bot.runtime import (
    get_bot,
    get_bot_error,
    get_bot_info,
    is_bot_paused,
    request_bot_restart,
    request_bot_start,
    request_bot_stop,
)
from web.deps import require_admin
from web.schemas.common import BotStatus
from web.services.bot_ipc import get_ipc

router = APIRouter(prefix="/bot", tags=["bot"], dependencies=[Depends(require_admin)])


@router.get("/status", response_model=BotStatus)
async def status_endpoint() -> BotStatus:
    # Prefer in-process info (we share an event loop with the bot when running
    # under main.py). Fall back to IPC if the bot hasn't been registered yet.
    info = get_bot_info()
    panel_mem = round(psutil.Process(os.getpid()).memory_info().rss / 1048576, 1)
    bot = get_bot()
    if bot is None:
        ipc = get_ipc()
        try:
            data = await ipc.call("status", {}, timeout=3.0)
            p = data.get("payload", {})
            bot_mem = p.get("memory_mb", 0.0)
            return BotStatus(
                online=p.get("online", False),
                latency_ms=p.get("latency_ms"),
                guild_count=p.get("guild_count", 0),
                user_count=p.get("user_count", 0),
                uptime_seconds=p.get("uptime_seconds", 0.0),
                memory_mb=bot_mem,
                panel_memory_mb=panel_mem,
                version=p.get("version", "0.0.0"),
                error=get_bot_error(),
                ping_error=p.get("ping_error"),
            )
        except Exception:  # noqa: BLE001
            pass
    # In-process mode: bot and panel share the same process, so
    # memory_mb (from bot._proc or get_bot_info offline) == panel_memory_mb.
    # Show the single RSS as the total and set panel to 0 to avoid
    # double-counting.
    bot_mem = info.get("memory_mb", 0.0)
    if bot_mem == panel_mem:
        panel_mem = 0.0
    return BotStatus(
        online=info["online"],
        latency_ms=info["latency_ms"],
        guild_count=info["guild_count"],
        user_count=info["user_count"],
        uptime_seconds=info["uptime_seconds"],
        memory_mb=bot_mem,
        panel_memory_mb=panel_mem,
        version=info["version"],
        error=get_bot_error(),
        ping_error=info.get("ping_error"),
    )


@router.post("/restart")
async def restart() -> dict:
    # Prefer in-process control when the bot lives in this process.
    if get_bot() is not None or is_bot_paused():
        await request_bot_restart()
        return {"ok": True, "mode": "in-process"}
    ipc = get_ipc()
    try:
        await ipc.call("restart", {"requested_at": time.time()}, timeout=3.0)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "bot offline") from exc
    return {"ok": True, "mode": "ipc"}


@router.post("/start")
async def bot_start() -> dict:
    request_bot_start()
    return {"ok": True}


@router.post("/stop")
async def bot_stop() -> dict:
    await request_bot_stop()
    return {"ok": True}


@router.post("/presence")
async def presence(payload: dict) -> dict:
    # Try in-process first
    bot = get_bot()
    if bot is not None:
        await bot.change_presence(activity=_build_activity(payload))
        return {"ok": True}

    # Fall back to IPC
    ipc = get_ipc()
    await ipc.call("presence", payload, timeout=3.0)
    return {"ok": True}
