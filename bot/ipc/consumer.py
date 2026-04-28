"""Bot IPC consumer: subscribes to ``cognix:bot:cmd`` and dispatches to handlers."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any

try:
    import redis.asyncio as aioredis
except ImportError:  # pragma: no cover
    aioredis = None  # type: ignore[assignment]

from config.constants import IPC_ACK_CHANNEL, IPC_CMD_CHANNEL
from config.logging import get_logger
from config.settings import get_settings

log = get_logger("bot.ipc")

Handler = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


class IpcConsumer:
    def __init__(self) -> None:
        self._handlers: dict[str, Handler] = {}
        self._redis = None
        self._task: asyncio.Task[None] | None = None

    def register(self, command: str, handler: Handler) -> None:
        self._handlers[command] = handler

    async def start(self) -> bool:
        settings = get_settings()
        if not settings.redis_enabled:
            log.info("bot_ipc_disabled", reason="redis_url_empty")
            return False
        if aioredis is None:
            log.warning("redis_unavailable_ipc_disabled")
            return False
        try:
            self._redis = aioredis.from_url(settings.redis_url, decode_responses=True)
            await self._redis.ping()
        except Exception as exc:  # noqa: BLE001
            log.warning("redis_connect_failed", error=str(exc))
            return False
        self._task = asyncio.create_task(self._loop(), name="bot-ipc-consumer")
        log.info("bot_ipc_started")
        return True

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
        if self._redis:
            await self._redis.aclose()

    async def publish_event(self, event: str, payload: dict[str, Any]) -> None:
        if self._redis is None:
            return
        await self._redis.publish(
            "cognix:events", json.dumps({"event": event, "payload": payload})
        )

    async def _loop(self) -> None:
        assert self._redis is not None
        ps = self._redis.pubsub()
        await ps.subscribe(IPC_CMD_CHANNEL)
        async for msg in ps.listen():
            if msg.get("type") != "message":
                continue
            try:
                data = json.loads(msg["data"])
                rid = data["request_id"]
                cmd = data["command"]
                payload = data.get("payload", {})
            except Exception as exc:  # noqa: BLE001
                log.warning("ipc_decode_failed", error=str(exc))
                continue
            asyncio.create_task(self._handle(rid, cmd, payload))

    async def _handle(self, rid: str, cmd: str, payload: dict[str, Any]) -> None:
        handler = self._handlers.get(cmd)
        if handler is None:
            await self._ack(rid, "error", error=f"unknown command: {cmd}")
            return
        try:
            result = await handler(payload)
            await self._ack(rid, "ok", payload=result)
        except Exception as exc:  # noqa: BLE001
            log.exception("ipc_handler_failed", command=cmd)
            await self._ack(rid, "error", error=str(exc))

    async def _ack(
        self, rid: str, status: str, *, payload: dict[str, Any] | None = None, error: str | None = None
    ) -> None:
        assert self._redis is not None
        msg = {"request_id": rid, "status": status, "payload": payload or {}}
        if error:
            msg["error"] = error
        await self._redis.publish(IPC_ACK_CHANNEL, json.dumps(msg))
