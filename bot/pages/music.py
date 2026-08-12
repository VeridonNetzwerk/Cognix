"""Music page and music API routes."""

from __future__ import annotations

import json

from fastapi import Cookie, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select

from bot.runtime import get_bot
from bot.database.models.music_playlist import MusicPlaylist
from bot.database.models.server import Server
from bot.database.session import db_session
from web.deps import ACCESS_COOKIE
from bot.pages._shared import _render, _require_cog, _require_user, router


@router.get("/music", response_class=HTMLResponse)
async def music_view(request: Request,
                     access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE)) -> HTMLResponse:
    user = await _require_user(access_token)
    _require_cog("bot.cogs.music")
    async with db_session() as s:
        servers = (await s.scalars(select(Server).order_by(Server.name))).all()
    servers_json = json.dumps(
        [{"id": str(srv.id), "name": srv.name} for srv in servers]
    )
    return _render(request, "music/music.html", user=user, servers_json=servers_json)


@router.get("/api/v1/music/{server_id}/state")
async def music_state_api(
    server_id: int,
    access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE),
):
    await _require_user(access_token)
    from bot.services.audio_player import get_manager
    mgr = get_manager()
    p = mgr.get_existing(server_id) if hasattr(mgr, "get_existing") else None
    if p is None:
        return {"connected": False, "current": None, "queue": [], "volume": 1.0, "loop": "off", "paused": False}
    return p.snapshot()


@router.post("/api/v1/music/{server_id}/play")
async def music_play_api(
    server_id: int,
    request: Request,
    access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE),
):
    user = await _require_user(access_token)
    body = await request.json()
    query = (body.get("query") or "").strip()
    if not query:
        raise HTTPException(400, "missing query")
    bot = get_bot()
    if bot is None:
        raise HTTPException(503, "bot offline")
    guild = bot.get_guild(server_id)
    if guild is None:
        raise HTTPException(404, "guild")
    from bot.services.audio_player import get_manager, search_tracks
    tracks = await search_tracks(query, requested_by=user.username)
    if not tracks:
        raise HTTPException(404, "no results")
    mgr = get_manager()
    player = mgr.get(bot, server_id)
    for t in tracks:
        player.add(t)
    await player.ensure_loop()
    return {"queued": len(tracks)}


@router.post("/api/v1/music/{server_id}/{action}")
async def music_action_api(
    server_id: int,
    action: str,
    request: Request,
    access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE),
):
    await _require_user(access_token)
    from bot.services.audio_player import get_manager
    mgr = get_manager()
    p = mgr.get_existing(server_id)
    if p is None:
        raise HTTPException(404, "no player")
    if action == "pause":
        await p.pause()
    elif action == "resume":
        await p.resume()
    elif action == "skip":
        await p.skip()
    elif action == "stop":
        await p.stop()
    elif action == "volume":
        body = await request.json()
        pct = int(body.get("percent", 100))
        p.set_volume(max(0, min(200, pct)) / 100.0)
    elif action == "loop":
        body = await request.json()
        mode = str(body.get("mode", "off"))
        if mode in ("off", "track", "queue"):
            p.loop = mode
    elif action == "shuffle":
        p.shuffle()
    else:
        raise HTTPException(400, "unknown action")
    return {"ok": True}


@router.get("/api/v1/music/{server_id}/playlists")
async def music_playlists_api(
    server_id: int,
    access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE),
):
    await _require_user(access_token)
    async with db_session() as s:
        rows = (
            await s.scalars(
                select(MusicPlaylist).where(MusicPlaylist.server_id == server_id).order_by(MusicPlaylist.name)
            )
        ).all()
    return [{"id": str(r.id), "name": r.name, "tracks": r.tracks} for r in rows]
