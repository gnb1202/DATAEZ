"""Tests for rate_limiter module — in-memory fallback limiter."""

import pytest
from fastapi import HTTPException

from app.rate_limiter import InMemoryRateLimiter


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

    def test_expired_events_cleaned(self):
        import time
        rl = InMemoryRateLimiter()
        # Use a very short window
        rl.check("key1", limit=1, window_seconds=0)
        # After window expires, should allow again
        time.sleep(0.01)
        rl.check("key1", limit=1, window_seconds=0)
