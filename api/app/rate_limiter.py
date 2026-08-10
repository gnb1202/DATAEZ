"""Rate limiter with Redis backend (falls back to in-memory if Redis unavailable)."""

import logging
import time
from collections import defaultdict, deque

import redis
from fastapi import HTTPException

from .config import settings

logger = logging.getLogger(__name__)

_TOO_MANY = "Too many requests. Please try again later."


class RedisRateLimiter:
    """Sliding-window rate limiter backed by Redis sorted sets."""

    def __init__(self, redis_url: str) -> None:
        self._redis = redis.from_url(redis_url, decode_responses=True)

    def check(self, key: str, limit: int, window_seconds: int) -> None:
        now = time.time()
        pipe = self._redis.pipeline()
        pipe.zremrangebyscore(key, 0, now - window_seconds)
        pipe.zcard(key)
        pipe.zadd(key, {f"{now}": now})
        pipe.expire(key, window_seconds)
        results = pipe.execute()
        current_count = results[1]
        if current_count >= limit:
            raise HTTPException(status_code=429, detail=_TOO_MANY)


class InMemoryRateLimiter:
    """Fallback sliding-window rate limiter (single-process only)."""

    def __init__(self) -> None:
        self._events: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str, limit: int, window_seconds: int) -> None:
        now = time.time()
        queue = self._events[key]
        cutoff = now - window_seconds
        while queue and queue[0] < cutoff:
            queue.popleft()
        if len(queue) >= limit:
            raise HTTPException(status_code=429, detail=_TOO_MANY)
        queue.append(now)


def _create_rate_limiter() -> RedisRateLimiter | InMemoryRateLimiter:
    try:
        rl = RedisRateLimiter(settings.redis_url)
        rl._redis.ping()
        logger.info("Rate limiter: using Redis at %s", settings.redis_url)
        return rl
    except Exception:
        logger.warning("Rate limiter: Redis unavailable, falling back to in-memory")
        return InMemoryRateLimiter()


rate_limiter = _create_rate_limiter()
