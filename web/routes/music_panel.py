"""Music control API — proxies commands to the bot.

Tries Redis IPC first (works when API and bot are separate processes).
Falls back to the in-process bot bridge when Redis IPC is disabled, so
the web panel still works under the single-process Pterodactyl deployment.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from web.deps import require_mod
from web.services.bot_ipc import get_ipc

router = APIRouter(prefix="/music", tags=["music"], dependencies=[Depends(require_mod)])


class PlayRequest(BaseModel):
    query: str


class VolumeRequest(BaseModel):
    value: int


# ----------------------- in-process fallback ------------------------------

def _empty_status(server_id: int) -> dict[str, Any]:
    return {"server_id": server_id, "playing": False, "queue": [],
            "title": "", "author": "", "volume": 100, "paused": False}


def _player_for(server_id: int):
    """Return the live wavelink Player for the guild, or None."""
    try:
        from bot.runtime import get_bot
    except Exception:  # noqa: BLE001
        return None
    bot = get_bot()
    if bot is None:
        return None
    guild = bot.get_guild(server_id)
    if guild is None:
        return None
    return guild.voice_client  # wavelink.Player or None


async def _local_status(server_id: int) -> dict[str, Any]:
    p = _player_for(server_id)
    if p is None:
        return _empty_status(server_id)
    current = getattr(p, "current", None)
    queue = list(getattr(p, "queue", []) or [])
    return {
        "server_id": server_id,
        "playing": bool(current),
        "paused": bool(getattr(p, "paused", False)),
        "title": getattr(current, "title", "") if current else "",
        "author": getattr(current, "author", "") if current else "",
        "volume": int(getattr(p, "volume", 100)),
        "queue": [{"title": getattr(t, "title", ""), "duration": ""}
                  for t in queue[:25]],
    }


async def _local_play(server_id: int, query: str) -> dict[str, Any]:
    try:
        import wavelink  # type: ignore[import-not-found]
    except ImportError as exc:
        raise HTTPException(503, "wavelink not installed") from exc
    from bot.runtime import get_bot

    bot = get_bot()
    if bot is None:
        raise HTTPException(503, "bot offline")
    guild = bot.get_guild(server_id)
    if guild is None:
        raise HTTPException(404, "guild not found")
    p = guild.voice_client
    if p is None:
        raise HTTPException(400, "Bot is not in a voice channel. Use /play in Discord first.")
    tracks = await wavelink.Playable.search(query)
    if not tracks:
        raise HTTPException(404, "no tracks found")
    track = tracks[0]
    if p.playing:
        p.queue.put(track)
        return {"queued": track.title}
    await p.play(track)
    return {"playing": track.title}


async def _local_action(server_id: int, action: str, value: int | None = None) -> dict[str, Any]:
    p = _player_for(server_id)
    if p is None:
        raise HTTPException(404, "no active player")
    if action == "pause":
        await p.pause(True)
    elif action == "resume":
        await p.pause(False)
    elif action == "skip":
        await p.skip(force=True)
    elif action == "stop":
        await p.disconnect()
    elif action == "volume" and value is not None:
        await p.set_volume(max(0, min(100, int(value))))
    else:
        raise HTTPException(400, "unknown action")
    return {"ok": True}


# ----------------------- IPC + fallback dispatcher -------------------------

async def _dispatch(command: str, payload: dict, *, fallback) -> dict:
    ipc = get_ipc()
    try:
        result = await ipc.call(command, payload, timeout=3.0)
        if result.get("status") == "ok":
            return result.get("payload", {})
    except Exception:  # noqa: BLE001
        pass  # fall through to in-process
    return await fallback()


# ----------------------- routes -------------------------------------------

@router.get("/{server_id}/status")
async def status_(server_id: int) -> dict:
    return await _dispatch("music.status", {"server_id": server_id},
                           fallback=lambda: _local_status(server_id))


@router.post("/{server_id}/play")
async def play(server_id: int, body: PlayRequest) -> dict:
    return await _dispatch("music.play",
                           {"server_id": server_id, "query": body.query},
                           fallback=lambda: _local_play(server_id, body.query))


@router.post("/{server_id}/pause")
async def pause(server_id: int) -> dict:
    return await _dispatch("music.pause", {"server_id": server_id},
                           fallback=lambda: _local_action(server_id, "pause"))


@router.post("/{server_id}/resume")
async def resume(server_id: int) -> dict:
    return await _dispatch("music.resume", {"server_id": server_id},
                           fallback=lambda: _local_action(server_id, "resume"))


@router.post("/{server_id}/skip")
async def skip(server_id: int) -> dict:
    return await _dispatch("music.skip", {"server_id": server_id},
                           fallback=lambda: _local_action(server_id, "skip"))


@router.post("/{server_id}/stop")
async def stop(server_id: int) -> dict:
    return await _dispatch("music.stop", {"server_id": server_id},
                           fallback=lambda: _local_action(server_id, "stop"))


@router.post("/{server_id}/volume")
async def volume(server_id: int, body: VolumeRequest) -> dict:
    return await _dispatch("music.volume",
                           {"server_id": server_id, "value": body.value},
                           fallback=lambda: _local_action(server_id, "volume", body.value))
