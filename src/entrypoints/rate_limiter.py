"""Unified rate limiter — Redis-backed token bucket для всех протоколов.

Multi-instance safety: все токены в Redis (atomic INCR/EXPIRE).
Поддерживает:
- Per-API-key rate limits
- Per-IP rate limits
- Per-action rate limits
- Global fallback rate

Интегрируется в BaseEntrypoint.dispatch() и FastAPI middleware.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

__all__ = ("RateLimitExceeded", "RedisRateLimiter", "get_rate_limiter")

logger = logging.getLogger("entrypoints.rate_limiter")


class RateLimitExceeded(Exception):
    """Raised when rate limit is exceeded."""

    def __init__(self, *, limit: int, window: int, retry_after: int):
        super().__init__(f"Rate limit exceeded: {limit}/{window}s, retry after {retry_after}s")
        self.limit = limit
        self.window = window
        self.retry_after = retry_after


@dataclass(slots=True)
class RateLimit:
    """Описание rate limit policy."""
    limit: int
    window_seconds: int
    key_prefix: str = "ratelimit"


class RedisRateLimiter:
    """Token bucket rate limiter на Redis.

    Использует Redis INCR + EXPIRE (atomic). Multi-instance safe.

    Usage::

        limiter = get_rate_limiter()
        try:
            await limiter.check("api_key:abc", RateLimit(limit=100, window_seconds=60))
        except RateLimitExceeded as exc:
            return {"error": str(exc), "retry_after": exc.retry_after}
    """

    async def check(
        self,
        identifier: str,
        policy: RateLimit,
    ) -> dict[str, Any]:
        """Проверяет и увеличивает счётчик. Raises RateLimitExceeded при превышении.

        Returns:
            {"remaining": int, "reset_at": int, "limit": int}
        """
        try:
            from app.infrastructure.clients.storage.redis import redis_client
        except ImportError:
            return {"remaining": policy.limit, "reset_at": 0, "limit": policy.limit}

        now = int(time.time())
        window_start = now - (now % policy.window_seconds)
        key = f"{policy.key_prefix}:{identifier}:{window_start}"

        try:
            raw = getattr(redis_client, "_raw_client", None) or redis_client
            pipe = raw.pipeline() if hasattr(raw, "pipeline") else None
            if pipe is not None:
                pipe.incr(key)
                pipe.expire(key, policy.window_seconds)
                results = await pipe.execute()
                count = int(results[0]) if results else 0
            else:
                count = await raw.incr(key)
                await raw.expire(key, policy.window_seconds)
        except Exception as exc:
            logger.warning("Rate limiter Redis failed (fail-open): %s", exc)
            return {"remaining": policy.limit, "reset_at": 0, "limit": policy.limit}

        reset_at = window_start + policy.window_seconds
        remaining = max(0, policy.limit - count)

        if count > policy.limit:
            raise RateLimitExceeded(
                limit=policy.limit,
                window=policy.window_seconds,
                retry_after=reset_at - now,
            )

        return {"remaining": remaining, "reset_at": reset_at, "limit": policy.limit}


_instance: RedisRateLimiter | None = None


def get_rate_limiter() -> RedisRateLimiter:
    global _instance
    if _instance is None:
        _instance = RedisRateLimiter()
    return _instance
