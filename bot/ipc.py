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

from bot.config.constants import IPC_ACK_CHANNEL, IPC_CMD_CHANNEL
from bot.config.logging import get_logger
from bot.config.settings import get_settings

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
        last_pong = asyncio.get_running_loop().time()
        PONG_TIMEOUT = 30.0  # seconds
        try:
            async for msg in ps.listen():
                # Periodic health-check: if Redis goes silent, abort the loop
                now = asyncio.get_running_loop().time()
                if now - last_pong > PONG_TIMEOUT:
                    log.warning("ipc_redis_dead", reconnecting=True)
                    break
                last_pong = now

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
                # Store task reference to prevent GC and capture exceptions
                task = asyncio.create_task(self._handle(rid, cmd, payload), name=f"ipc-{cmd}")
                task.add_done_callback(
                    lambda t: t.exception()
                    and log.warning("ipc_handler_crashed", command=cmd, error=str(t.exception()))
                )
        except Exception as exc:  # noqa: BLE001
            log.warning("ipc_loop_error", error=str(exc))
        finally:
            try:
                await ps.unsubscribe(IPC_CMD_CHANNEL)
            except Exception:  # noqa: BLE001
                pass
            log.info("ipc_consumer_exited", reason="redis_disconnected")

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
