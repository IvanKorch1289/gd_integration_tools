"""Тесты unified rate-limiter (Sprint 1 V16 Single-Entry, Step 3.2)."""

# ruff: noqa: S101

from __future__ import annotations

from src.backend.core.resilience.rate_limiter import (
    RateLimit,
    RateLimiter,
    RateLimitExceeded,
    RedisRateLimiter,
    get_rate_limiter,
)


def test_rate_limit_dataclass() -> None:
    """``RateLimit`` сериализуется с разумными дефолтами."""
    policy = RateLimit(limit=100, window_seconds=60)
    assert policy.limit == 100
    assert policy.window_seconds == 60
    assert policy.key_prefix == "ratelimit"


def test_rate_limit_exceeded_carries_retry_after() -> None:
    """``RateLimitExceeded`` несёт ``retry_after`` в секундах."""
    exc = RateLimitExceeded(limit=10, window=60, retry_after=42)
    assert exc.limit == 10
    assert exc.window == 60
    assert exc.retry_after == 42
    assert "42s" in str(exc)


def test_rate_limiter_protocol_runtime_check() -> None:
    """``RedisRateLimiter`` удовлетворяет ``RateLimiter`` Protocol."""
    instance = get_rate_limiter()
    assert isinstance(instance, RedisRateLimiter)
    assert isinstance(instance, RateLimiter)


def test_get_rate_limiter_singleton() -> None:
    """``get_rate_limiter`` возвращает стабильный singleton."""
    a = get_rate_limiter()
    b = get_rate_limiter()
    assert a is b


def test_infrastructure_shim_re_exports() -> None:
    """Backward-compat: импорты из ``infrastructure`` всё ещё работают."""
    from src.backend.infrastructure.resilience.unified_rate_limiter import (
        RateLimit as InfraLimit,
    )
    from src.backend.infrastructure.resilience.unified_rate_limiter import (
        RateLimitExceeded as InfraExceeded,
    )
    from src.backend.infrastructure.resilience.unified_rate_limiter import (
        RedisRateLimiter as InfraRedis,
    )

    assert InfraLimit is RateLimit
    assert InfraExceeded is RateLimitExceeded
    assert InfraRedis is RedisRateLimiter
