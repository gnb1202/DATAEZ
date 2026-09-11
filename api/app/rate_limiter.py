"""Local sliding windows, or atomic PostgreSQL windows for serverless."""

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


class DatabaseRateLimiter:
    def check(self, key: str, limit: int, window_seconds: int) -> None:
        import hashlib
        from . import db
        digest = hashlib.sha256(key.encode()).hexdigest()
        try:
            with db._connect() as conn:
                conn.execute("SET LOCAL statement_timeout = '5s'")
                # Bounded reclamation; no IPs, emails or JWTs are stored.
                conn.execute("""DELETE FROM request_limits WHERE key_hash IN (
                    SELECT key_hash FROM request_limits WHERE expires_at < clock_timestamp()
                    ORDER BY expires_at LIMIT 100 FOR UPDATE SKIP LOCKED)""")
                row = conn.execute("""INSERT INTO request_limits(key_hash,used,expires_at)
                    VALUES(%s,1,clock_timestamp()+(%s * interval '1 second'))
                    ON CONFLICT(key_hash) DO UPDATE SET
                      used=CASE WHEN request_limits.expires_at<=clock_timestamp() THEN 1 ELSE request_limits.used+1 END,
                      expires_at=CASE WHEN request_limits.expires_at<=clock_timestamp() THEN EXCLUDED.expires_at ELSE request_limits.expires_at END
                    WHERE request_limits.expires_at<=clock_timestamp() OR request_limits.used<%s
                    RETURNING used""", (digest, window_seconds, limit)).fetchone()
        except Exception:
            # Do not silently lose cost protection when the shared store fails.
            raise HTTPException(503, '요청 한도를 확인할 수 없습니다. 잠시 후 다시 시도해주세요.') from None
        if not row:
            raise HTTPException(429, _TOO_MANY, headers={'Retry-After': str(window_seconds)})


from .config import settings
rate_limiter = DatabaseRateLimiter() if settings.runtime_mode == 'serverless' else InMemoryRateLimiter()


def check_ai_budget(user_id):
    """Count admitted attempts, including errors/disconnects, never refund them."""
    if settings.runtime_mode != 'serverless':
        return
    rate_limiter.check(f'ai-day:user:{user_id}', settings.ai_user_requests_per_day, 86400)
    rate_limiter.check('ai-day:application', settings.ai_total_requests_per_day, 86400)
