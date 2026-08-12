"""Common schemas used across multiple routes."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class ServerOut(BaseModel):
    id: str
    name: str
    icon_hash: str | None
    member_count: int
    is_active: bool


class ModerationActionOut(BaseModel):
    id: str
    server_id: str
    action_type: str
    target_id: str | None
    moderator_id: str
    reason: str
    created_at: datetime
    expires_at: datetime | None
    affected_count: int


class ModerationRequest(BaseModel):
    server_ids: list[str]
    target_user_id: str | None = None
    reason: str = ""
    duration_seconds: int | None = None
    message_count: int | None = None


class BotStatus(BaseModel):
    online: bool
    latency_ms: float | None
    guild_count: int
    user_count: int
    uptime_seconds: float
    memory_mb: float
    version: str


class StatsPoint(BaseModel):
    day: str
    count: int


class StatsSeries(BaseModel):
    metric: str
    points: list[StatsPoint]
