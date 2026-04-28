"""In-memory + Redis sliding-window rate limiter."""

from __future__ import annotations

import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

try:
    import redis.asyncio as aioredis
except ImportError:  # pragma: no cover
    aioredis = None  # type: ignore[assignment]

from config.settings import get_settings


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Simple per-IP rate limit. Buckets defined by path prefix.

    Defaults: 120 req/min globally; 10 req/min on /auth/login.
    """

    def __init__(self, app, *, default: tuple[int, int] = (120, 60)) -> None:
        super().__init__(app)
        self._default = default
        self._mem: dict[str, list[float]] = {}
        self._redis = None

    async def _get_redis(self):
        if aioredis is None:
            return None
        settings = get_settings()
        if not settings.redis_enabled:
            return None
        if self._redis is None:
            try:
                self._redis = aioredis.from_url(settings.redis_url, decode_responses=True)
                await self._redis.ping()
            except Exception:  # noqa: BLE001
                self._redis = None
        return self._redis

    def _bucket_for(self, path: str) -> tuple[int, int]:
        if path.startswith("/api/v1/auth/login"):
            return (10, 60)
        if path.startswith("/api/v1/setup"):
            return (30, 60)
        return self._default

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        client_ip = (
            request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
            or (request.client.host if request.client else "unknown")
        )
        limit, window = self._bucket_for(request.url.path)
        key = f"rl:{client_ip}:{request.url.path}"
        now = time.time()

        redis = await self._get_redis()
        allowed = True
        if redis is not None:
            try:
                pipe = redis.pipeline()
                pipe.zremrangebyscore(key, 0, now - window)
                pipe.zadd(key, {f"{now}": now})
                pipe.zcard(key)
                pipe.expire(key, window)
                _, _, count, _ = await pipe.execute()
                allowed = int(count) <= limit
            except Exception:  # noqa: BLE001
                allowed = self._mem_allow(key, now, limit, window)
        else:
            allowed = self._mem_allow(key, now, limit, window)

        if not allowed:
            return JSONResponse({"error": "rate_limited"}, status_code=429)
        return await call_next(request)

    def _mem_allow(self, key: str, now: float, limit: int, window: int) -> bool:
        bucket = self._mem.setdefault(key, [])
        cutoff = now - window
        i = 0
        for i, ts in enumerate(bucket):  # noqa: B007
            if ts >= cutoff:
                break
        del bucket[:i]
        bucket.append(now)
        return len(bucket) <= limit
