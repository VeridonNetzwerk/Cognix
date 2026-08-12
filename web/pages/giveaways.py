"""Giveaways routes."""

from __future__ import annotations

import uuid
from datetime import UTC
from datetime import datetime as _dt
from datetime import timedelta as _td

from fastapi import Cookie, Form, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import desc, select

from bot.runtime import get_bot
from bot.database.models.audit_log import AuditLog
from bot.database.models.giveaway import Giveaway, GiveawayStatus
from bot.database.models.server import Server
from bot.database.session import db_session
from web.deps import ACCESS_COOKIE
from web.pages._shared import _render, _require_cog, _require_user, router


@router.get("/giveaways", response_class=HTMLResponse)
async def giveaways_view(request: Request,
                         access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE)) -> HTMLResponse:
    user = await _require_user(access_token)
    _require_cog("bot.cogs.giveaway")
    async with db_session() as s:
        rows = (
            await s.scalars(
                select(Giveaway).order_by(desc(Giveaway.created_at)).limit(200)
            )
        ).all()
        servers = (await s.scalars(select(Server).order_by(Server.name))).all()
    return _render(request, "giveaways.html", user=user, giveaways=rows, servers=servers)


@router.get("/giveaways/{giveaway_id}", response_class=HTMLResponse)
async def giveaway_detail_view(
    giveaway_id: str,
    request: Request,
    access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE),
) -> HTMLResponse:
    user = await _require_user(access_token)
    _require_cog("bot.cogs.giveaway")
    try:
        gid = uuid.UUID(giveaway_id)
    except ValueError as exc:
        raise HTTPException(404) from exc
    async with db_session() as s:
        g = await s.get(Giveaway, gid)
        if g is None:
            raise HTTPException(404)
        server = await s.get(Server, g.server_id)
    return _render(
        request,
        "giveaway_detail.html",
        user=user,
        g=g,
        server=server,
    )


@router.post("/giveaways/{giveaway_id}/end")
async def giveaways_end(giveaway_id: str,
                         access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE)) -> Response:
    user = await _require_user(access_token)
    _require_cog("bot.cogs.giveaway")
    async with db_session() as s:
        g = await s.get(Giveaway, uuid.UUID(giveaway_id))
        if g is None:
            raise HTTPException(404)
        g.ended = True
        g.status = GiveawayStatus.ENDED
        s.add(AuditLog(actor_id=user.id, action="giveaway.end", target=str(g.id)))
    bot = get_bot()
    if bot is not None:
        cog = bot.get_cog("Giveaways")
        if cog is not None:
            try:
                await cog._end_giveaway(uuid.UUID(giveaway_id))  # type: ignore[attr-defined]
            except Exception:
                pass
    return RedirectResponse("/giveaways", status_code=303)


@router.post("/giveaways/{giveaway_id}/delete")
async def giveaways_delete(giveaway_id: str,
                           access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE)) -> Response:
    user = await _require_user(access_token)
    _require_cog("bot.cogs.giveaway")
    async with db_session() as s:
        g = await s.get(Giveaway, uuid.UUID(giveaway_id))
        if g is not None:
            s.add(AuditLog(actor_id=user.id, action="giveaway.delete", target=str(g.id)))
            await s.delete(g)
    return RedirectResponse("/giveaways", status_code=303)


@router.post("/giveaways/{giveaway_id}/reroll")
async def giveaways_reroll(giveaway_id: str,
                            access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE)) -> Response:
    user = await _require_user(access_token)
    _require_cog("bot.cogs.giveaway")
    async with db_session() as s:
        g = await s.get(Giveaway, uuid.UUID(giveaway_id))
        if g is None:
            raise HTTPException(404)
        s.add(AuditLog(actor_id=user.id, action="giveaway.reroll", target=str(g.id)))
    bot = get_bot()
    if bot is not None:
        cog = bot.get_cog("Giveaways")
        if cog is not None:
            try:
                async with db_session() as s2:
                    g2 = await s2.get(Giveaway, uuid.UUID(giveaway_id))
                    channel = bot.get_channel(g2.channel_id) if g2 else None
                    if g2 is not None and channel is not None:
                        winners = await cog._draw_winners(g2, channel)  # type: ignore[attr-defined]
                        g2.winners = winners
                        if winners:
                            try:
                                mentions = ", ".join(f"<@{w}>" for w in winners)
                                await channel.send(
                                    f"\N{PARTY POPPER} New winners for **{g2.prize}**: {mentions}"
                                )
                            except Exception:
                                pass
            except Exception:
                pass
    return RedirectResponse(f"/giveaways/{giveaway_id}", status_code=303)


@router.post("/giveaways/{giveaway_id}/extend")
async def giveaways_extend(giveaway_id: str,
                            additional_seconds: int = Form(...),
                            access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE)) -> Response:
    user = await _require_user(access_token)
    _require_cog("bot.cogs.giveaway")
    extra = max(60, min(60 * 60 * 24 * 30, int(additional_seconds)))
    async with db_session() as s:
        g = await s.get(Giveaway, uuid.UUID(giveaway_id))
        if g is None:
            raise HTTPException(404)
        if g.ended:
            g.ended = False
            g.status = GiveawayStatus.ACTIVE
        g.ends_at = g.ends_at + _td(seconds=extra)
        s.add(AuditLog(actor_id=user.id, action="giveaway.extend",
                       target=str(g.id), details={"seconds": extra}))
    return RedirectResponse(f"/giveaways/{giveaway_id}", status_code=303)


@router.post("/giveaways/{giveaway_id}/edit")
async def giveaways_edit(giveaway_id: str,
                          prize: str = Form(...),
                          winner_count: int = Form(...),
                          access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE)) -> Response:
    user = await _require_user(access_token)
    _require_cog("bot.cogs.giveaway")
    prize = (prize or "").strip()[:256]
    if not prize:
        raise HTTPException(400, "prize required")
    wc = max(1, min(50, int(winner_count)))
    async with db_session() as s:
        g = await s.get(Giveaway, uuid.UUID(giveaway_id))
        if g is None:
            raise HTTPException(404)
        g.prize = prize
        g.winner_count = wc
        s.add(AuditLog(actor_id=user.id, action="giveaway.edit", target=str(g.id)))
    return RedirectResponse(f"/giveaways/{giveaway_id}", status_code=303)


@router.post("/giveaways/create")
async def giveaways_create(
    request: Request,
    server_id: str = Form(...),
    channel_id: str = Form(...),
    prize: str = Form(...),
    winners: int = Form(default=1),
    duration: str = Form(...),
    required_role_id: str | None = Form(default=None),
    access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE),
) -> Response:
    me = await _require_user(access_token)
    _require_cog("bot.cogs.giveaway")
    prize = (prize or "").strip()[:256]
    if not prize:
        raise HTTPException(400, "prize required")
    bot = get_bot()
    if bot is None:
        raise HTTPException(503, "bot offline")
    from bot.cogs.giveaway import PARTY, _build_embed, _parse_duration
    delta = _parse_duration(duration)
    if delta is None:
        raise HTTPException(400, "invalid duration (use e.g. 30m, 2h, 1d)")
    import discord as _d
    guild = bot.get_guild(int(server_id))
    if guild is None:
        raise HTTPException(404, "guild not found")
    channel = guild.get_channel(int(channel_id))
    if not isinstance(channel, _d.TextChannel):
        raise HTTPException(400, "channel must be a text channel")
    role_id_int: int | None = None
    if required_role_id and str(required_role_id).strip().isdigit():
        role_id_int = int(required_role_id)
    ends_at = _dt.now(tz=UTC) + delta
    g = Giveaway(
        server_id=guild.id,
        channel_id=channel.id,
        message_id=0,
        prize=prize,
        winner_count=max(1, min(50, int(winners))),
        ends_at=ends_at,
        host_id=int(getattr(bot.user, "id", 0) or 0),
        required_role_id=role_id_int,
        winners=[],
    )
    try:
        msg = await channel.send(embed=_build_embed(g))
        await msg.add_reaction(PARTY)
    except _d.HTTPException as exc:
        raise HTTPException(400, f"discord error: {exc}") from exc
    g.message_id = msg.id
    async with db_session() as s:
        s.add(g)
        await s.flush()
        new_id = g.id
        s.add(AuditLog(actor_id=me.id, action="giveaway.create", target=str(new_id),
                       details={"prize": prize, "channel_id": str(channel.id)}))
    return RedirectResponse(f"/giveaways/{new_id}", status_code=303)
