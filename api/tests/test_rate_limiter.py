"""Request limits, concurrent admission and cleanup without external services."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from fastapi import HTTPException

from app.rate_limiter import InMemoryRateLimiter


@pytest.fixture
def clock(monkeypatch):
    now = [100.0]
    monkeypatch.setattr("app.rate_limiter.monotonic", lambda: now[0])
    return now


class TestInMemoryRateLimiter:
    def test_allows_under_limit(self):
        rl = InMemoryRateLimiter()
        # Should not raise
        for _ in range(5):
            rl.check("key1", limit=5, window_seconds=60)

    def test_blocks_over_limit(self):
        rl = InMemoryRateLimiter()
        for _ in range(3):
            rl.check("key1", limit=3, window_seconds=60)
        with pytest.raises(HTTPException) as exc:
            rl.check("key1", limit=3, window_seconds=60)
        assert exc.value.status_code == 429

    def test_different_keys_independent(self):
        rl = InMemoryRateLimiter()
        for _ in range(3):
            rl.check("key-a", limit=3, window_seconds=60)
        # Different key should not be blocked
        rl.check("key-b", limit=3, window_seconds=60)

    def test_request_expires_at_window_boundary(self, clock):
        rl = InMemoryRateLimiter()
        rl.check("key1", limit=1, window_seconds=60)
        clock[0] = 159.999
        with pytest.raises(HTTPException):
            rl.check("key1", limit=1, window_seconds=60)
        clock[0] = 160.0
        rl.check("key1", limit=1, window_seconds=60)

    def test_blocked_requests_do_not_extend_window(self, clock):
        rl = InMemoryRateLimiter()
        rl.check("key1", limit=1, window_seconds=60)
        for now in (130.0, 150.0, 159.0):
            clock[0] = now
            with pytest.raises(HTTPException):
                rl.check("key1", limit=1, window_seconds=60)
        clock[0] = 160.0
        rl.check("key1", limit=1, window_seconds=60)
        assert len(rl._windows["key1"].events) == 1

    def test_cleanup_reclaims_inactive_keys_without_resetting_active_limit(self, clock):
        rl = InMemoryRateLimiter()
        for i in range(1000):
            rl.check(f"one-off:{i}", limit=1, window_seconds=60)
        clock[0] = 159.0
        rl.check("active", limit=1, window_seconds=60)
        clock[0] = 160.0
        with pytest.raises(HTTPException):
            rl.check("active", limit=1, window_seconds=60)
        assert set(rl._windows) == {"active"}

    def test_cleanup_respects_different_key_windows(self, clock):
        rl = InMemoryRateLimiter()
        rl.check("short", limit=1, window_seconds=10)
        rl.check("long", limit=1, window_seconds=300)
        clock[0] = 160.0
        with pytest.raises(HTTPException):
            rl.check("long", limit=1, window_seconds=300)
        assert "short" not in rl._windows
        clock[0] = 400.0
        rl.check("long", limit=1, window_seconds=300)

    def test_concurrent_requests_cannot_exceed_limit(self, clock):
        rl = InMemoryRateLimiter()
        barrier = Barrier(16)

        def requests(_):
            barrier.wait(timeout=10)
            admitted = 0
            for _ in range(4):
                try:
                    rl.check("shared", limit=7, window_seconds=60)
                    admitted += 1
                except HTTPException as exc:
                    assert exc.status_code == 429
            return admitted

        with ThreadPoolExecutor(max_workers=16) as pool:
            assert sum(pool.map(requests, range(16))) == 7
        clock[0] = 160.0
        rl.check("shared", limit=7, window_seconds=60)
