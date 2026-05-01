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
from database.models.music_play_history import MusicPlayHistory
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


# ----- Playlist CRUD (FEAT #1) -----

class PlaylistCreate(BaseModel):
    name: str
    tracks: list[dict] | None = None


class PlaylistRename(BaseModel):
    name: str


class PlaylistAddTrack(BaseModel):
    query: str | None = None
    title: str | None = None
    url: str | None = None
    duration: int | None = 0
    thumbnail: str | None = ""


def _normalize_track(t: dict) -> dict:
    return {
        "query": (t.get("query") or t.get("url") or t.get("title") or "").strip(),
        "title": (t.get("title") or "").strip() or "Untitled",
        "url": (t.get("url") or "").strip(),
        "duration": int(t.get("duration") or 0),
        "thumbnail": (t.get("thumbnail") or "").strip(),
    }


@router.post("/{server_id}/playlists")
async def playlist_create(server_id: int, body: PlaylistCreate) -> dict:
    name = body.name.strip()
    if not name:
        raise HTTPException(400, "name required")
    if len(name) > 128:
        raise HTTPException(400, "name too long")
    tracks = [_normalize_track(t) for t in (body.tracks or [])]
    async with db_session() as s:
        existing = await s.scalar(
            select(MusicPlaylist).where(
                MusicPlaylist.server_id == server_id,
                MusicPlaylist.name == name,
            )
        )
        if existing is not None:
            raise HTTPException(409, "playlist already exists")
        row = MusicPlaylist(
            server_id=server_id,
            name=name,
            created_by=0,  # web-created — no Discord user attached
            tracks=tracks,
        )
        s.add(row)
        await s.flush()
        return {"id": str(row.id), "name": row.name, "tracks": row.tracks}


@router.delete("/{server_id}/playlists/{playlist_id}")
async def playlist_delete(server_id: int, playlist_id: str) -> dict:
    import uuid as _uuid
    try:
        pid = _uuid.UUID(playlist_id)
    except ValueError as exc:
        raise HTTPException(400, "invalid id") from exc
    async with db_session() as s:
        row = await s.get(MusicPlaylist, pid)
        if row is None or row.server_id != server_id:
            raise HTTPException(404, "not found")
        await s.delete(row)
    return {"ok": True}


@router.patch("/{server_id}/playlists/{playlist_id}")
async def playlist_rename(server_id: int, playlist_id: str, body: PlaylistRename) -> dict:
    import uuid as _uuid
    name = body.name.strip()
    if not name or len(name) > 128:
        raise HTTPException(400, "invalid name")
    try:
        pid = _uuid.UUID(playlist_id)
    except ValueError as exc:
        raise HTTPException(400, "invalid id") from exc
    async with db_session() as s:
        row = await s.get(MusicPlaylist, pid)
        if row is None or row.server_id != server_id:
            raise HTTPException(404, "not found")
        row.name = name
    return {"ok": True, "name": name}


@router.post("/{server_id}/playlists/{playlist_id}/tracks")
async def playlist_add_track(server_id: int, playlist_id: str, body: PlaylistAddTrack) -> dict:
    import uuid as _uuid
    try:
        pid = _uuid.UUID(playlist_id)
    except ValueError as exc:
        raise HTTPException(400, "invalid id") from exc
    raw = body.dict()
    if not (raw.get("query") or raw.get("url") or raw.get("title")):
        raise HTTPException(400, "track requires query/url/title")
    async with db_session() as s:
        row = await s.get(MusicPlaylist, pid)
        if row is None or row.server_id != server_id:
            raise HTTPException(404, "not found")
        new_tracks = list(row.tracks or [])
        new_tracks.append(_normalize_track(raw))
        row.tracks = new_tracks
    return {"ok": True, "count": len(new_tracks)}


@router.delete("/{server_id}/playlists/{playlist_id}/tracks/{index}")
async def playlist_remove_track(server_id: int, playlist_id: str, index: int) -> dict:
    import uuid as _uuid
    try:
        pid = _uuid.UUID(playlist_id)
    except ValueError as exc:
        raise HTTPException(400, "invalid id") from exc
    async with db_session() as s:
        row = await s.get(MusicPlaylist, pid)
        if row is None or row.server_id != server_id:
            raise HTTPException(404, "not found")
        tracks = list(row.tracks or [])
        if not (0 <= index < len(tracks)):
            raise HTTPException(404, "index out of range")
        tracks.pop(index)
        row.tracks = tracks
    return {"ok": True, "count": len(tracks)}


@router.post("/{server_id}/playlists/{playlist_id}/play")
async def playlist_play(server_id: int, playlist_id: str) -> dict:
    """Enqueue every track in a playlist into the live GuildPlayer."""
    import uuid as _uuid
    try:
        pid = _uuid.UUID(playlist_id)
    except ValueError as exc:
        raise HTTPException(400, "invalid id") from exc
    bot = _bot()
    if bot is None:
        raise HTTPException(503, "bot offline")
    if not yt_dlp_available():
        raise HTTPException(503, "yt-dlp not installed")
    guild = bot.get_guild(server_id)
    if guild is None:
        raise HTTPException(404, "guild not found")
    if guild.voice_client is None:
        raise HTTPException(400, "Bot is not in a voice channel — use /play in Discord first.")
    async with db_session() as s:
        row = await s.get(MusicPlaylist, pid)
        if row is None or row.server_id != server_id:
            raise HTTPException(404, "playlist not found")
        tracks_data = list(row.tracks or [])

    p = get_manager().get(bot, server_id)
    queued = 0
    for t in tracks_data:
        q = t.get("url") or t.get("query") or t.get("title")
        if not q:
            continue
        # Use cached metadata where possible — keeps the request snappy even
        # for big playlists. Still resolves stream URLs lazily on play.
        try:
            tracks = await search_tracks(q, limit=1)
        except Exception:
            tracks = []
        for tr in tracks:
            p.add(tr)
            queued += 1
    await p.ensure_loop()
    return {"ok": True, "queued": queued}


# ----- Play history (FEAT #2) -----

@router.get("/{server_id}/history")
async def history_latest(server_id: int, limit: int = 50) -> dict:
    """Most-recently-played tracks for a guild."""
    limit = max(1, min(200, int(limit)))
    from sqlalchemy import desc
    async with db_session() as s:
        rows = (await s.scalars(
            select(MusicPlayHistory)
            .where(MusicPlayHistory.server_id == server_id)
            .order_by(desc(MusicPlayHistory.played_at))
            .limit(limit)
        )).all()
    return {
        "items": [
            {
                "id": r.id,
                "title": r.title,
                "url": r.url,
                "thumbnail": r.thumbnail,
                "duration": r.duration,
                "played_by": r.played_by,
                "played_at": r.played_at.isoformat() if r.played_at else None,
            }
            for r in rows
        ]
    }


@router.get("/{server_id}/history/top")
async def history_top(server_id: int, limit: int = 25) -> dict:
    """Most-played tracks for a guild (grouped by url-or-title)."""
    limit = max(1, min(100, int(limit)))
    from sqlalchemy import func as _f
    key_col = _f.coalesce(_f.nullif(MusicPlayHistory.url, ""), MusicPlayHistory.title)
    async with db_session() as s:
        rows = (await s.execute(
            select(
                key_col.label("k"),
                _f.max(MusicPlayHistory.title).label("title"),
                _f.max(MusicPlayHistory.url).label("url"),
                _f.max(MusicPlayHistory.thumbnail).label("thumbnail"),
                _f.count(MusicPlayHistory.id).label("plays"),
                _f.max(MusicPlayHistory.played_at).label("last_played"),
            )
            .where(MusicPlayHistory.server_id == server_id)
            .group_by(key_col)
            .order_by(_f.count(MusicPlayHistory.id).desc())
            .limit(limit)
        )).all()
    return {
        "items": [
            {
                "title": r.title,
                "url": r.url,
                "thumbnail": r.thumbnail,
                "plays": int(r.plays),
                "last_played": r.last_played.isoformat() if r.last_played else None,
            }
            for r in rows
        ]
    }
