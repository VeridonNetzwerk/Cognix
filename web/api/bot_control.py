"""Bot control routes (status, restart, presence)."""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends, HTTPException, status

from bot.runtime import (
    get_bot,
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
    if get_bot() is None:
        ipc = get_ipc()
        try:
            data = await ipc.call("status", {}, timeout=3.0)
            p = data.get("payload", {})
            return BotStatus(
                online=p.get("online", False),
                latency_ms=p.get("latency_ms"),
                guild_count=p.get("guild_count", 0),
                user_count=p.get("user_count", 0),
                uptime_seconds=p.get("uptime_seconds", 0.0),
                memory_mb=p.get("memory_mb", 0.0),
                version=p.get("version", "0.0.0"),
            )
        except Exception:  # noqa: BLE001
            pass
    return BotStatus(
        online=info["online"],
        latency_ms=info["latency_ms"],
        guild_count=info["guild_count"],
        user_count=info["user_count"],
        uptime_seconds=info["uptime_seconds"],
        memory_mb=0.0,
        version=info["version"],
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
    ipc = get_ipc()
    await ipc.call("presence", payload, timeout=3.0)
    return {"ok": True}
