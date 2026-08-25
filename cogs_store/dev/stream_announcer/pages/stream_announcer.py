"""Stream announcer dashboard routes — settings and live streams."""

from __future__ import annotations

from typing import Any

from fastapi import Cookie, Form, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import desc, select

from bot.config.logging import get_logger
from bot.runtime import get_bot
from bot.database.models.auth.audit_log import AuditLog
from bot.database.models.stream_announcer.stream_announcer import (
    StreamAnnouncerConfig,
    StreamSession,
)
from bot.database.session import db_session
from web.deps import ACCESS_COOKIE
from bot.pages._shared import (
    _render,
    _require_cog,
    _require_user,
    _get_selected_server_id,
    router,
)

log = get_logger("web.pages.stream_announcer")


@router.get("/stream-announcer", response_class=HTMLResponse)
async def stream_announcer_view(
    request: Request,
    access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE),
) -> HTMLResponse:
    user = await _require_user(access_token)
    _require_cog("cogs.stream_announcer.stream_announcer")
    server_id = _get_selected_server_id(request)

    cfg: StreamAnnouncerConfig | None = None
    active_streams: list[dict[str, Any]] = []
    channels: list[dict[str, Any]] = []
    roles: list[dict[str, Any]] = []
    total_streams = 0

    if server_id:
        bot = get_bot()
        guild = bot.get_guild(server_id) if bot else None
        if guild:
            channels = [
                {"id": c.id, "name": c.name}
                for c in guild.text_channels
            ]
            roles = [
                {"id": r.id, "name": r.name}
                for r in guild.roles
                if r.is_assignable() and r.id != guild.id
            ]

        async with db_session() as s:
            cfg = await s.get(StreamAnnouncerConfig, server_id)
            if cfg is None:
                cfg = StreamAnnouncerConfig(server_id=server_id)
                s.add(cfg)

            active = (await s.scalars(
                select(StreamSession)
                .where(
                    StreamSession.server_id == server_id,
                    StreamSession.is_active.is_(True),
                )
                .order_by(desc(StreamSession.started_at))
            )).all()

            for sess in active:
                member = guild.get_member(sess.user_id) if guild else None
                active_streams.append({
                    "user_id": sess.user_id,
                    "name": member.display_name if member else f"User {sess.user_id}",
                    "avatar_url": str(member.display_avatar.url) if member else "",
                    "platform": sess.platform,
                    "stream_title": sess.stream_title,
                    "stream_url": sess.stream_url,
                    "game": sess.game,
                    "started_at": sess.started_at,
                })

            from sqlalchemy import func as sa_func
            total_streams = (await s.scalar(
                select(sa_func.count(StreamSession.id)).where(
                    StreamSession.server_id == server_id
                )
            )) or 0

    return _render(
        request,
        "stream_announcer/stream_announcer.html",
        user=user,
        cfg=cfg,
        active_streams=active_streams,
        channels=channels,
        roles=roles,
        total_streams=total_streams,
        selected_server_id=server_id,
    )


@router.post("/stream-announcer/save")
async def stream_announcer_save(
    server_id: int = Form(...),
    enabled: str = Form(default=""),
    announce_channel_id: str = Form(default=""),
    announce_message: str = Form(default="🔴 **{user.name}** is now streaming!\n**{stream_title}**\n{stream_url}"),
    tracked_platforms: str = Form(default=""),
    tracked_roles: str = Form(default=""),
    ignored_roles: str = Form(default=""),
    streaming_role_id: str = Form(default=""),
    delete_on_end: str = Form(default=""),
    ping_role_id: str = Form(default=""),
    cooldown_minutes: int = Form(default=60),
    access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE),
) -> Response:
    user = await _require_user(access_token)
    _require_cog("cogs.stream_announcer.stream_announcer")

    def _form_bool(v: str) -> bool:
        return v.lower() in ("on", "true", "1", "yes")

    def _form_id_list(v: str) -> list[int]:
        ids: list[int] = []
        for part in v.split(","):
            part = part.strip()
            if part.isdigit():
                ids.append(int(part))
        return ids

    async with db_session() as s:
        cfg = await s.get(StreamAnnouncerConfig, int(server_id))
        if cfg is None:
            cfg = StreamAnnouncerConfig(server_id=int(server_id))
            s.add(cfg)
        cfg.enabled = _form_bool(enabled)
        cfg.announce_channel_id = int(announce_channel_id) if announce_channel_id.strip().isdigit() else None
        cfg.announce_message = announce_message
        cfg.tracked_platforms = [p.strip() for p in tracked_platforms.split(",") if p.strip()] if tracked_platforms.strip() else []
        cfg.tracked_roles = _form_id_list(tracked_roles)
        cfg.ignored_roles = _form_id_list(ignored_roles)
        cfg.streaming_role_id = int(streaming_role_id) if streaming_role_id.strip().isdigit() else None
        cfg.delete_on_end = _form_bool(delete_on_end)
        cfg.ping_role_id = int(ping_role_id) if ping_role_id.strip().isdigit() else None
        cfg.cooldown_minutes = max(0, cooldown_minutes)
        s.add(AuditLog(actor_id=user.id, action="stream_announcer.save", target=str(server_id)))
    return RedirectResponse("/stream-announcer", status_code=303)
