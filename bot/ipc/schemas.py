"""IPC schemas for bot ↔ API communication."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class IpcMessage(BaseModel):
    request_id: str
    command: str
    payload: dict[str, Any]


class IpcAck(BaseModel):
    request_id: str
    status: str  # "ok" | "error"
    payload: dict[str, Any] = {}
    error: str | None = None
