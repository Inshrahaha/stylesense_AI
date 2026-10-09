"""
Rate limiting middleware using Redis.

Per-IP and per-account limits on auth endpoints,
per-user limits on upload and LLM-backed endpoints.
"""

from datetime import datetime, UTC
from typing import Any

from app.config import get_settings
from app.core.logging import get_logger

logger = get_logger("rate_limit")


class RateLimiter:
    """
    Simple sliding window rate limiter backed by Redis.
    Falls back to in-memory dict when Redis is unavailable (dev/test).
    """

    def __init__(self, redis_client: Any = None):
        self._redis = redis_client
        self._memory_store: dict[str, list[float]] = {}

    async def is_rate_limited(
        self, key: str, max_requests: int, window_seconds: int = 60
    ) -> bool:
        """
        Check if the given key has exceeded the rate limit.
        Returns True if limited, False if allowed.
        """
        if self._redis:
            return await self._redis_check(key, max_requests, window_seconds)
        return self._memory_check(key, max_requests, window_seconds)

    async def _redis_check(
        self, key: str, max_requests: int, window_seconds: int
    ) -> bool:
        """Redis-backed sliding window counter."""
        now = datetime.now(UTC).timestamp()
        window_start = now - window_seconds
        pipe_key = f"rate_limit:{key}"

        pipe = self._redis.pipeline()
        pipe.zremrangebyscore(pipe_key, 0, window_start)
        pipe.zadd(pipe_key, {str(now): now})
        pipe.zcard(pipe_key)
        pipe.expire(pipe_key, window_seconds)
        results = await pipe.execute()

        count = results[2]
        if count > max_requests:
            logger.warning(
                "Rate limit exceeded",
                extra={"key": key, "count": count, "limit": max_requests},
            )
            return True
        return False

    def _memory_check(
        self, key: str, max_requests: int, window_seconds: int
    ) -> bool:
        """In-memory fallback for dev/test."""
        now = datetime.now(UTC).timestamp()
        window_start = now - window_seconds

        if key not in self._memory_store:
            self._memory_store[key] = []

        # Clean old entries
        self._memory_store[key] = [
            ts for ts in self._memory_store[key] if ts > window_start
        ]

        if len(self._memory_store[key]) >= max_requests:
            return True

        self._memory_store[key].append(now)
        return False

    async def get_remaining(
        self, key: str, max_requests: int, window_seconds: int = 60
    ) -> int:
        """Get remaining requests in the current window."""
        if self._redis:
            now = datetime.now(UTC).timestamp()
            window_start = now - window_seconds
            pipe_key = f"rate_limit:{key}"
            await self._redis.zremrangebyscore(pipe_key, 0, window_start)
            count = await self._redis.zcard(pipe_key)
            return max(0, max_requests - count)
        else:
            now = datetime.now(UTC).timestamp()
            window_start = now - window_seconds
            entries = [
                ts for ts in self._memory_store.get(key, []) if ts > window_start
            ]
            return max(0, max_requests - len(entries))
