"""Process-local request limits for the single-worker demo/deployment."""

from collections import deque
from dataclasses import dataclass, field
from threading import Lock
from time import monotonic

from fastapi import HTTPException

_TOO_MANY = "Too many requests. Please try again later."


@dataclass
class _Window:
    events: deque[float] = field(default_factory=deque)
    expires_at: float = 0.0


class InMemoryRateLimiter:
    """Thread-safe sliding window; counters reset when this process restarts."""

    def __init__(self) -> None:
        self._windows: dict[str, _Window] = {}
        self._lock = Lock()
        self._next_cleanup = 0.0

    def check(self, key: str, limit: int, window_seconds: int) -> None:
        # Sync endpoints run on multiple threads even with one Uvicorn worker.
        # Read time inside the lock to keep each queue ordered under contention.
        with self._lock:
            now = monotonic()
            if now >= self._next_cleanup:
                expired = [key for key, window in self._windows.items() if window.expires_at <= now]
                for expired_key in expired:
                    del self._windows[expired_key]
                self._next_cleanup = now + 60

            window = self._windows.setdefault(key, _Window())
            cutoff = now - window_seconds
            while window.events and window.events[0] <= cutoff:
                window.events.popleft()
            if len(window.events) >= limit:
                raise HTTPException(status_code=429, detail=_TOO_MANY)
            window.events.append(now)
            window.expires_at = now + window_seconds


rate_limiter = InMemoryRateLimiter()
