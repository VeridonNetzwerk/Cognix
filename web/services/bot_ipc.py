"""Redis-based IPC client used by the API to issue commands and receive events."""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any

try:
    import redis.asyncio as aioredis
except ImportError:  # pragma: no cover
    aioredis = None  # type: ignore[assignment]

from config.constants import IPC_ACK_CHANNEL, IPC_CMD_CHANNEL, IPC_EVENT_CHANNEL
from config.settings import get_settings

_client: "BotIpc | None" = None


class BotIpc:
    """Async IPC client. Falls back to a dummy mode if Redis unavailable."""

    def __init__(self) -> None:
        self._redis = None
        self._pubsub = None
        self._pending: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._ack_listener: asyncio.Task[None] | None = None
        self._event_subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self._event_listener: asyncio.Task[None] | None = None
        self._connected = False

    async def connect(self) -> bool:
        if aioredis is None:
            return False
        if self._connected:
            return True
        settings = get_settings()
        if not settings.redis_enabled:
            return False
        try:
            self._redis = aioredis.from_url(settings.redis_url, decode_responses=True)
            await self._redis.ping()
        except Exception:  # noqa: BLE001
            self._redis = None
            return False
        self._connected = True
        self._ack_listener = asyncio.create_task(self._listen_acks(), name="ipc-ack-listener")
        self._event_listener = asyncio.create_task(self._listen_events(), name="ipc-evt-listener")
        return True

    async def close(self) -> None:
        for task in (self._ack_listener, self._event_listener):
            if task is not None:
                task.cancel()
        if self._redis is not None:
            await self._redis.aclose()
        self._connected = False

    async def call(self, command: str, payload: dict[str, Any], *, timeout: float = 5.0) -> dict[str, Any]:
        if not self._connected and not await self.connect():
            raise RuntimeError("bot IPC unavailable (Redis not reachable)")
        request_id = uuid.uuid4().hex
        fut: asyncio.Future[dict[str, Any]] = asyncio.get_event_loop().create_future()
        self._pending[request_id] = fut
        msg = {"request_id": request_id, "command": command, "payload": payload}
        await self._redis.publish(IPC_CMD_CHANNEL, json.dumps(msg))  # type: ignore[union-attr]
        try:
            return await asyncio.wait_for(fut, timeout=timeout)
        finally:
            self._pending.pop(request_id, None)

    async def publish_event(self, event: str, payload: dict[str, Any]) -> None:
        if not self._connected and not await self.connect():
            return
        await self._redis.publish(  # type: ignore[union-attr]
            IPC_EVENT_CHANNEL, json.dumps({"event": event, "payload": payload})
        )

    def subscribe_events(self) -> asyncio.Queue[dict[str, Any]]:
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=1024)
        self._event_subscribers.add(q)
        return q

    def unsubscribe_events(self, q: asyncio.Queue[dict[str, Any]]) -> None:
        self._event_subscribers.discard(q)

    async def _listen_acks(self) -> None:
        assert self._redis is not None
        ps = self._redis.pubsub()
        await ps.subscribe(IPC_ACK_CHANNEL)
        async for msg in ps.listen():
            if msg.get("type") != "message":
                continue
            try:
                data = json.loads(msg["data"])
            except Exception:  # noqa: BLE001
                continue
            rid = data.get("request_id")
            fut = self._pending.get(rid)
            if fut and not fut.done():
                fut.set_result(data)

    async def _listen_events(self) -> None:
        assert self._redis is not None
        ps = self._redis.pubsub()
        await ps.subscribe(IPC_EVENT_CHANNEL)
        async for msg in ps.listen():
            if msg.get("type") != "message":
                continue
            try:
                data = json.loads(msg["data"])
            except Exception:  # noqa: BLE001
                continue
            for q in list(self._event_subscribers):
                try:
                    q.put_nowait(data)
                except asyncio.QueueFull:
                    pass


def get_ipc() -> BotIpc:
    global _client
    if _client is None:
        _client = BotIpc()
    return _client
