"""Common schemas used across multiple routes."""

from __future__ import annotations

from datetime import datetime
from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int


class ServerOut(BaseModel):
    id: str
    name: str
    icon_hash: str | None
    member_count: int
    is_active: bool


class CogStateOut(BaseModel):
    cog_name: str
    server_id: str | None
    enabled: bool


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


class StatsPoint(BaseModel):
    day: str
    count: int


class StatsSeries(BaseModel):
    metric: str
    points: list[StatsPoint]


class BotStatus(BaseModel):
    online: bool
    latency_ms: float | None
    guild_count: int
    user_count: int
    uptime_seconds: float
    memory_mb: float
    version: str
