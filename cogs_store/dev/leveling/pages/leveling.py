"""Leveling dashboard routes — settings, leaderboard, role rewards."""

from __future__ import annotations

from typing import Any

import discord
from fastapi import Cookie, Form, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import desc, select

from bot.config.logging import get_logger
from bot.runtime import get_bot
from bot.database.models.auth.audit_log import AuditLog
from bot.database.models.leveling.leveling import (
    LevelingConfig,
    LevelingRoleReward,
    LevelingUser,
)
from bot.database.models.server.server import Server
from bot.database.session import db_session
from web.deps import ACCESS_COOKIE
from bot.pages._shared import (
    _render,
    _require_cog,
    _require_user,
    _get_selected_server_id,
    router,
)

log = get_logger("web.pages.leveling")


@router.get("/leveling", response_class=HTMLResponse)
async def leveling_view(
    request: Request,
    access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE),
) -> HTMLResponse:
    user = await _require_user(access_token)
    _require_cog("cogs.leveling.leveling")
    server_id = _get_selected_server_id(request)

    cfg: LevelingConfig | None = None
    leaderboard: list[dict[str, Any]] = []
    rewards: list[LevelingRoleReward] = []
    channels: list[dict[str, Any]] = []
    roles: list[dict[str, Any]] = []
    total_users = 0
    total_messages = 0

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
            cfg = await s.get(LevelingConfig, server_id)
            if cfg is None:
                cfg = LevelingConfig(server_id=server_id)
                s.add(cfg)

            rows = (
                await s.scalars(
                    select(LevelingUser)
                    .where(LevelingUser.server_id == server_id)
                    .order_by(desc(LevelingUser.xp))
                    .limit(50)
                )
            ).all()
            for r in rows:
                member = guild.get_member(r.user_id) if guild else None
                leaderboard.append({
                    "user_id": r.user_id,
                    "name": member.display_name if member else f"User {r.user_id}",
                    "avatar_url": str(member.display_avatar.url) if member else "",
                    "xp": r.xp,
                    "level": r.level,
                    "messages": r.messages,
                })

            rewards = (
                await s.scalars(
                    select(LevelingRoleReward)
                    .where(LevelingRoleReward.server_id == server_id)
                    .order_by(LevelingRoleReward.level)
                )
            ).all()

            from sqlalchemy import func as sa_func
            count_result = await s.scalar(
                select(sa_func.count(LevelingUser.id)).where(
                    LevelingUser.server_id == server_id
                )
            )
            total_users = count_result or 0
            msg_result = await s.scalar(
                select(sa_func.sum(LevelingUser.messages)).where(
                    LevelingUser.server_id == server_id
                )
            )
            total_messages = msg_result or 0

    return _render(
        request,
        "leveling/leveling.html",
        user=user,
        cfg=cfg,
        leaderboard=leaderboard,
        rewards=rewards,
        channels=channels,
        roles=roles,
        total_users=total_users,
        total_messages=total_messages,
        selected_server_id=server_id,
    )


@router.post("/leveling/save")
async def leveling_save(
    server_id: int = Form(...),
    enabled: str = Form(default=""),
    xp_per_message_min: int = Form(default=15),
    xp_per_message_max: int = Form(default=25),
    cooldown_seconds: int = Form(default=60),
    formula_base: int = Form(default=100),
    formula_multiplier: int = Form(default=50),
    formula_exponent: int = Form(default=10),
    levelup_channel_id: str = Form(default=""),
    levelup_message: str = Form(default="🎉 {user.mention} reached level **{level}**!"),
    levelup_dm: str = Form(default=""),
    xp_multiplier: float = Form(default=1.0),
    stack_rewards: str = Form(default=""),
    ignored_channels: str = Form(default=""),
    ignored_roles: str = Form(default=""),
    access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE),
) -> Response:
    user = await _require_user(access_token)
    _require_cog("cogs.leveling.leveling")

    def _form_bool(v: str) -> bool:
        return v.lower() in ("on", "true", "1", "yes")

    def _form_channel_list(v: str) -> list[int]:
        ids: list[int] = []
        for part in v.split(","):
            part = part.strip()
            if part.isdigit():
                ids.append(int(part))
        return ids

    async with db_session() as s:
        cfg = await s.get(LevelingConfig, int(server_id))
        if cfg is None:
            cfg = LevelingConfig(server_id=int(server_id))
            s.add(cfg)
        cfg.enabled = _form_bool(enabled)
        cfg.xp_per_message_min = max(1, xp_per_message_min)
        cfg.xp_per_message_max = max(cfg.xp_per_message_min, xp_per_message_max)
        cfg.cooldown_seconds = max(0, cooldown_seconds)
        cfg.formula_base = max(0, formula_base)
        cfg.formula_multiplier = max(0, formula_multiplier)
        cfg.formula_exponent = max(0, formula_exponent)
        cfg.levelup_channel_id = int(levelup_channel_id) if levelup_channel_id.strip().isdigit() else None
        cfg.levelup_message = levelup_message
        cfg.levelup_dm = _form_bool(levelup_dm)
        cfg.xp_multiplier = max(0.0, xp_multiplier)
        cfg.stack_rewards = _form_bool(stack_rewards)
        cfg.ignored_channels = _form_channel_list(ignored_channels)
        cfg.ignored_roles = _form_channel_list(ignored_roles)
        s.add(AuditLog(actor_id=user.id, action="leveling.save", target=str(server_id)))
    return RedirectResponse("/leveling", status_code=303)


@router.post("/leveling/reward/add")
async def leveling_reward_add(
    server_id: int = Form(...),
    level: int = Form(...),
    role_id: int = Form(...),
    role_name: str = Form(default=""),
    access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE),
) -> Response:
    user = await _require_user(access_token)
    _require_cog("cogs.leveling.leveling")

    async with db_session() as s:
        existing = await s.scalar(
            select(LevelingRoleReward).where(
                LevelingRoleReward.server_id == int(server_id),
                LevelingRoleReward.level == level,
            )
        )
        if existing:
            existing.role_id = role_id
            existing.role_name = role_name
        else:
            s.add(LevelingRoleReward(
                server_id=int(server_id),
                level=level,
                role_id=role_id,
                role_name=role_name,
            ))
        s.add(AuditLog(actor_id=user.id, action="leveling.reward_add", target=str(server_id)))
    return RedirectResponse("/leveling", status_code=303)


@router.post("/leveling/reward/delete")
async def leveling_reward_delete(
    reward_id: int = Form(...),
    access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE),
) -> Response:
    user = await _require_user(access_token)
    _require_cog("cogs.leveling.leveling")

    async with db_session() as s:
        reward = await s.get(LevelingRoleReward, reward_id)
        if reward:
            await s.delete(reward)
            s.add(AuditLog(actor_id=user.id, action="leveling.reward_delete", target=str(reward_id)))
    return RedirectResponse("/leveling", status_code=303)
