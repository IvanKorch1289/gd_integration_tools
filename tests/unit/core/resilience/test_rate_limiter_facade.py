"""S104 W2 — tests для rate limiter facade canonical re-export."""
from __future__ import annotations

from src.backend.core.resilience.rate_limiter_facade import (
    RateLimit,
    RateLimitExceeded,
    RedisRateLimiter,
    get_rate_limiter,
)
from src.backend.infrastructure.resilience import unified_rate_limiter as _src


def test_redis_rate_limiter_identity() -> None:
    """``RedisRateLimiter`` re-export identity."""
    assert RedisRateLimiter is _src.RedisRateLimiter


def test_rate_limit_exceeded_identity() -> None:
    """``RateLimitExceeded`` re-export identity."""
    assert RateLimitExceeded is _src.RateLimitExceeded


def test_rate_limit_dataclass_identity() -> None:
    """``RateLimit`` re-export identity."""
    assert RateLimit is _src.RateLimit


def test_get_rate_limiter_identity() -> None:
    """``get_rate_limiter`` re-export identity."""
    assert get_rate_limiter is _src.get_rate_limiter


def test_get_rate_limiter_returns_instance() -> None:
    """``get_rate_limiter()`` returns singleton instance."""
    limiter = get_rate_limiter()
    assert isinstance(limiter, RedisRateLimiter)
    # Singleton: same instance on subsequent calls
    limiter2 = get_rate_limiter()
    assert limiter is limiter2
