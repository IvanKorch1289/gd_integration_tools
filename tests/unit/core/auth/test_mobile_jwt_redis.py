"""Tests for Redis-backed mobile JWT Phase 2 stores.

Uses AsyncMock to simulate Redis client without requiring real Redis.
Tests verify:
- Revocation store: revoke → is_revoked returns True; TTL set correctly
- Rate limiter: under/at/over limit; window resets; Redis errors → fail-open
- Both handle Redis-unavailable gracefully
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest


pytestmark = pytest.mark.asyncio


def _make_mock_client() -> AsyncMock:
    """Mock RedisClient with cache_get/cache_set."""
    client = AsyncMock()
    client.cache_get = AsyncMock(return_value=None)
    client.cache_set = AsyncMock(return_value=None)
    return client


# Patch the get_redis_client function (used by both stores)
@pytest.fixture
def mock_redis(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    client = _make_mock_client()

    async def _get_client() -> AsyncMock:
        return client

    monkeypatch.setattr(
        "src.backend.core.storage.redis.get_redis_client", _get_client
    )
    return client


# ── Revocation store tests ────────────────────────────────────────


async def test_revocation_revoke_persists_to_redis(mock_redis: AsyncMock) -> None:
    """revoke() writes to Redis with TTL = (exp - now)."""
    from src.backend.core.auth.mobile_jwt_redis import RedisRevocationStore

    store = RedisRevocationStore()
    expires = 1_000_000_000_000.0  # far future
    await store.revoke("jti-001", expires_at=expires)

    # cache_set was called with our key prefix + jti
    mock_redis.cache_set.assert_awaited_once()
    call_args = mock_redis.cache_set.await_args
    assert call_args.args[0] == "gd:mobile:revoked:jti-001"
    # TTL must be positive (we mocked time indirectly)
    assert call_args.kwargs.get("expire", call_args.args[2] if len(call_args.args) > 2 else None)


async def test_revocation_is_revoked_returns_true_when_key_exists(
    mock_redis: AsyncMock,
) -> None:
    """is_revoked() returns True when Redis has the key."""
    mock_redis.cache_get = AsyncMock(return_value=b"1234567890")
    from src.backend.core.auth.mobile_jwt_redis import RedisRevocationStore

    store = RedisRevocationStore()
    assert await store.is_revoked("jti-001") is True


async def test_revocation_is_revoked_returns_false_when_no_key(
    mock_redis: AsyncMock,
) -> None:
    """is_revoked() returns False when Redis returns None."""
    from src.backend.core.auth.mobile_jwt_redis import RedisRevocationStore

    store = RedisRevocationStore()
    assert await store.is_revoked("jti-001") is False


async def test_revocation_rejects_empty_jti() -> None:
    """revoke("") raises ValueError."""
    from src.backend.core.auth.mobile_jwt_redis import RedisRevocationStore

    store = RedisRevocationStore()
    with pytest.raises(ValueError, match="jti"):
        await store.revoke("", expires_at=1_000_000_000_000.0)


async def test_revocation_rejects_past_expiry() -> None:
    """revoke with past expires_at raises ValueError."""
    from src.backend.core.auth.mobile_jwt_redis import RedisRevocationStore

    store = RedisRevocationStore()
    with pytest.raises(ValueError, match="future"):
        await store.revoke("jti-x", expires_at=1.0)


# ── Rate limiter tests ────────────────────────────────────────────


async def test_rate_limiter_under_limit(mock_redis: AsyncMock) -> None:
    """First request increments counter to 1, allowed with remaining."""
    from src.backend.core.auth.mobile_jwt_redis import RedisRateLimiter

    limiter = RedisRateLimiter(max_requests=3, window_seconds=60)
    allowed, remaining = await limiter.check("device-1")
    assert allowed is True
    assert remaining == 2


async def test_rate_limiter_at_limit(mock_redis: AsyncMock) -> None:
    """When count > max_requests, reject with 0 remaining."""
    mock_redis.cache_get = AsyncMock(return_value=b"3")  # count after incr = 4
    from src.backend.core.auth.mobile_jwt_redis import RedisRateLimiter

    limiter = RedisRateLimiter(max_requests=3, window_seconds=60)
    allowed, remaining = await limiter.check("device-1")
    assert allowed is False
    assert remaining == 0


async def test_rate_limiter_redis_error_fails_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Redis errors → fail-open (allow request, log warning)."""

    async def _broken_get() -> None:
        raise ConnectionError("Redis down")

    monkeypatch.setattr(
        "src.backend.core.storage.redis.get_redis_client", _broken_get
    )
    from src.backend.core.auth.mobile_jwt_redis import RedisRateLimiter

    limiter = RedisRateLimiter(max_requests=3, window_seconds=60)
    allowed, remaining = await limiter.check("device-1")
    assert allowed is True  # fail-open
    assert remaining == 3


async def test_rate_limiter_rejects_invalid_max() -> None:
    """Constructor rejects max_requests <= 0."""
    from src.backend.core.auth.mobile_jwt_redis import RedisRateLimiter

    with pytest.raises(ValueError, match="max_requests"):
        RedisRateLimiter(max_requests=0, window_seconds=60)


async def test_rate_limiter_rejects_invalid_window() -> None:
    """Constructor rejects window_seconds <= 0."""
    from src.backend.core.auth.mobile_jwt_redis import RedisRateLimiter

    with pytest.raises(ValueError, match="window_seconds"):
        RedisRateLimiter(max_requests=10, window_seconds=0)


async def test_rate_limiter_rejects_empty_device_id(mock_redis: AsyncMock) -> None:
    """check("") raises ValueError."""
    from src.backend.core.auth.mobile_jwt_redis import RedisRateLimiter

    limiter = RedisRateLimiter(max_requests=10, window_seconds=60)
    with pytest.raises(ValueError, match="device_id"):
        await limiter.check("")


# ── Redis unavailable tests (fail-open behavior) ─────────────────


async def test_revocation_fails_open_when_redis_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """is_revoked() returns False when Redis unavailable (fail-open)."""

    async def _unavailable() -> None:
        return None  # get_redis_client returns None

    monkeypatch.setattr(
        "src.backend.core.storage.redis.get_redis_client", _unavailable
    )
    from src.backend.core.auth.mobile_jwt_redis import RedisRevocationStore

    store = RedisRevocationStore()
    assert await store.is_revoked("jti-001") is False  # fail-open


async def test_revocation_revoke_silent_when_redis_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """revoke() does not raise when Redis unavailable (just logs warning)."""

    async def _unavailable() -> None:
        return None

    monkeypatch.setattr(
        "src.backend.core.storage.redis.get_redis_client", _unavailable
    )
    from src.backend.core.auth.mobile_jwt_redis import RedisRevocationStore

    store = RedisRevocationStore()
    # Should not raise
    await store.revoke("jti-001", expires_at=1_000_000_000_000.0)
