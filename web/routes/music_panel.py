"""Music control API — bridges the dashboard to the in-process bot.

All endpoints operate on the live :class:`GuildPlayer` provided by
``bot.services.audio_player``. The legacy wavelink/IPC paths were removed
because the bot now uses native discord.py voice + yt-dlp.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from bot.services.audio_player import (
    Track,
    get_manager,
    search_tracks,
    yt_dlp_available,
)
from database.models.music_playlist import MusicPlaylist
from database.session import db_session
from sqlalchemy import select
from web.deps import require_mod

router = APIRouter(prefix="/music", tags=["music"], dependencies=[Depends(require_mod)])


# ----- Schemas -----

class PlayRequest(BaseModel):
    query: str


class VolumeRequest(BaseModel):
    percent: int


class LoopRequest(BaseModel):
    mode: str  # off | track | queue


class SearchRequest(BaseModel):
    query: str
    limit: int = 5


class ReorderRequest(BaseModel):
    src: int
    dst: int


# ----- Helpers -----

def _bot():
    try:
        from bot.runtime import get_bot
    except Exception:  # noqa: BLE001
        return None
    return get_bot()


def _player_for(server_id: int):
    bot = _bot()
    if bot is None:
        return None
    return get_manager().get_existing(server_id)


def _state(server_id: int) -> dict[str, Any]:
    p = _player_for(server_id)
    if p is None:
        return {
            "server_id": server_id,
            "current": None,
            "queue": [],
            "volume": 1.0,
            "loop": "off",
            "is_playing": False,
            "is_paused": False,
            "position": 0,
        }
    return p.snapshot()


# ----- State / status -----

@router.get("/{server_id}/state")
async def state(server_id: int) -> dict:
    return _state(server_id)


# Legacy alias used by the old UI:
@router.get("/{server_id}/status")
async def status_(server_id: int) -> dict:
    return _state(server_id)


# ----- Search (autocomplete dropdown) -----

@router.post("/{server_id}/search")
async def search(server_id: int, body: SearchRequest) -> dict:
    if not yt_dlp_available():
        raise HTTPException(503, "yt-dlp not installed")
    q = body.query.strip()
    if not q:
        return {"results": []}
    if not (q.startswith("http://") or q.startswith("https://") or q.startswith("ytsearch")):
        q = f"ytsearch{max(1, min(10, body.limit))}:{q}"
    tracks = await search_tracks(q, limit=max(1, min(10, body.limit)))
    return {"results": [t.to_dict() for t in tracks]}


# ----- Play / enqueue -----

@router.post("/{server_id}/play")
async def play(server_id: int, body: PlayRequest) -> dict:
    bot = _bot()
    if bot is None:
        raise HTTPException(503, "bot offline")
    if not yt_dlp_available():
        raise HTTPException(503, "yt-dlp not installed")
    guild = bot.get_guild(server_id)
    if guild is None:
        raise HTTPException(404, "guild not found")
    vc = guild.voice_client
    if vc is None:
        raise HTTPException(400, "Bot is not in a voice channel — use /play in Discord first.")
    tracks = await search_tracks(body.query, limit=1)
    if not tracks:
        raise HTTPException(404, "no tracks found")
    p = get_manager().get(bot, server_id)
    for t in tracks:
        p.add(t)
    await p.ensure_loop()
    return {"queued": tracks[0].title, "queue_size": len(p.queue)}


# ----- Transport -----

@router.post("/{server_id}/pause")
async def pause(server_id: int) -> dict:
    p = _player_for(server_id)
    if p is None:
        raise HTTPException(404, "no active player")
    await p.pause()
    return {"ok": True}


@router.post("/{server_id}/resume")
async def resume(server_id: int) -> dict:
    p = _player_for(server_id)
    if p is None:
        raise HTTPException(404, "no active player")
    await p.resume()
    return {"ok": True}


@router.post("/{server_id}/skip")
async def skip(server_id: int) -> dict:
    p = _player_for(server_id)
    if p is None:
        raise HTTPException(404, "no active player")
    await p.skip()
    return {"ok": True}


@router.post("/{server_id}/stop")
async def stop(server_id: int) -> dict:
    p = _player_for(server_id)
    if p is None:
        raise HTTPException(404, "no active player")
    await p.stop()
    return {"ok": True}


@router.post("/{server_id}/shuffle")
async def shuffle(server_id: int) -> dict:
    p = _player_for(server_id)
    if p is None:
        raise HTTPException(404, "no active player")
    p.shuffle()
    return {"ok": True}


@router.post("/{server_id}/volume")
async def volume(server_id: int, body: VolumeRequest) -> dict:
    p = _player_for(server_id)
    if p is None:
        raise HTTPException(404, "no active player")
    p.set_volume(max(0, min(200, int(body.percent))) / 100.0)
    return {"ok": True, "volume": p.volume}


@router.post("/{server_id}/loop")
async def loop_(server_id: int, body: LoopRequest) -> dict:
    p = _player_for(server_id)
    if p is None:
        raise HTTPException(404, "no active player")
    if body.mode not in ("off", "track", "queue"):
        raise HTTPException(400, "mode must be off/track/queue")
    p.loop = body.mode
    return {"ok": True, "loop": p.loop}


# ----- Queue manipulation -----

@router.delete("/{server_id}/queue/{index}")
async def queue_remove(server_id: int, index: int) -> dict:
    p = _player_for(server_id)
    if p is None:
        raise HTTPException(404, "no active player")
    removed = p.remove(index)
    if removed is None:
        raise HTTPException(404, "index out of range")
    return {"ok": True}


@router.post("/{server_id}/queue/reorder")
async def queue_reorder(server_id: int, body: ReorderRequest) -> dict:
    p = _player_for(server_id)
    if p is None:
        raise HTTPException(404, "no active player")
    if not (0 <= body.src < len(p.queue)):
        raise HTTPException(400, "src out of range")
    track = p.queue.pop(body.src)
    dst = max(0, min(len(p.queue), body.dst))
    p.queue.insert(dst, track)
    return {"ok": True}


# ----- Playlists (per-server) -----

@router.get("/{server_id}/playlists")
async def playlists(server_id: int) -> dict:
    async with db_session() as s:
        rows = (await s.scalars(
            select(MusicPlaylist).where(MusicPlaylist.server_id == server_id)
        )).all()
        return {
            "items": [
                {"id": str(r.id), "name": r.name, "tracks": r.tracks or []}
                for r in rows
            ]
        }
