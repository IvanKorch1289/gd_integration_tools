"""Unit tests for mobile JWT Phase 2: revocation + rate limiting.

Tests cover:
1. InMemoryRevocationStore: revoke / is_revoked / cleanup_expired
2. DeviceRateLimiter: under-limit / at-limit / over-limit / window-expiry
3. Constructor validation (max_requests > 0, window_seconds > 0)
"""

from __future__ import annotations

import time

import pytest

from src.backend.core.auth.mobile_jwt_revocation import (
    DeviceRateLimiter,
    InMemoryRevocationStore,
    RateLimitDecision,
)


pytestmark = pytest.mark.asyncio


# ── Revocation store tests ────────────────────────────────────────


async def test_revocation_store_revoke_and_check() -> None:
    """revoke(jti) → is_revoked(jti) returns True."""
    store = InMemoryRevocationStore()
    expires = time.time() + 3600
    await store.revoke("jti-001", expires_at=expires)
    assert await store.is_revoked("jti-001") is True
    assert await store.is_revoked("jti-002") is False


async def test_revocation_store_auto_expires() -> None:
    """Expired revocations auto-clear on is_revoked check."""
    store = InMemoryRevocationStore()
    # Already-expired revocation (1 second in past)
    expires = time.time() - 1
    await store.revoke("jti-expired", expires_at=time.time() + 1)
    # Now manually expire by setting in past
    store._revoked["jti-expired"] = store._revoked["jti-expired"].__class__(
        jti="jti-expired",
        revoked_at=store._revoked["jti-expired"].revoked_at,
        expires_at=expires,
    )
    assert await store.is_revoked("jti-expired") is False
    assert "jti-expired" not in store._revoked


async def test_revocation_store_cleanup_expired() -> None:
    """cleanup_expired() removes expired entries, returns count."""
    store = InMemoryRevocationStore()
    # Add one future, one past
    await store.revoke("jti-future", expires_at=time.time() + 3600)
    await store.revoke("jti-past", expires_at=time.time() + 1)
    # Manually mark past as expired
    past_record = store._revoked["jti-past"]
    store._revoked["jti-past"] = past_record.__class__(
        jti=past_record.jti,
        revoked_at=past_record.revoked_at,
        expires_at=time.time() - 1,
    )
    removed = await store.cleanup_expired()
    assert removed == 1
    assert "jti-past" not in store._revoked
    assert "jti-future" in store._revoked


async def test_revocation_store_rejects_empty_jti() -> None:
    """revoke("") raises ValueError."""
    store = InMemoryRevocationStore()
    with pytest.raises(ValueError, match="jti"):
        await store.revoke("", expires_at=time.time() + 3600)


async def test_revocation_store_rejects_past_expiry() -> None:
    """revoke with past expires_at raises ValueError."""
    store = InMemoryRevocationStore()
    with pytest.raises(ValueError, match="future"):
        await store.revoke("jti-x", expires_at=time.time() - 1)


# ── Rate limiter tests ────────────────────────────────────────────


async def test_rate_limiter_allows_under_limit() -> None:
    """First N requests within window are allowed."""
    limiter = DeviceRateLimiter(max_requests=3, window_seconds=60)
    for i in range(3):
        decision = await limiter.check("device-1")
        assert decision.allowed is True
        assert decision.remaining == 2 - i


async def test_rate_limiter_rejects_at_limit() -> None:
    """4th request within window is rejected."""
    limiter = DeviceRateLimiter(max_requests=3, window_seconds=60)
    for _ in range(3):
        await limiter.check("device-1")
    decision = await limiter.check("device-1")
    assert decision.allowed is False
    assert decision.remaining == 0


async def test_rate_limiter_isolates_devices() -> None:
    """Different devices have independent counters."""
    limiter = DeviceRateLimiter(max_requests=2, window_seconds=60)
    # Saturate device-1
    await limiter.check("device-1")
    await limiter.check("device-1")
    decision_1 = await limiter.check("device-1")
    assert decision_1.allowed is False
    # device-2 still has quota
    decision_2 = await limiter.check("device-2")
    assert decision_2.allowed is True


async def test_rate_limiter_window_expiry() -> None:
    """After window expires, quota resets."""
    limiter = DeviceRateLimiter(max_requests=2, window_seconds=0.5)
    await limiter.check("device-x")
    await limiter.check("device-x")
    # Over limit
    decision = await limiter.check("device-x")
    assert decision.allowed is False
    # Wait for window to slide past
    import asyncio

    await asyncio.sleep(0.6)
    decision = await limiter.check("device-x")
    assert decision.allowed is True


async def test_rate_limiter_rejects_invalid_max_requests() -> None:
    """Constructor rejects max_requests <= 0."""
    with pytest.raises(ValueError, match="max_requests"):
        DeviceRateLimiter(max_requests=0, window_seconds=60)


async def test_rate_limiter_rejects_invalid_window() -> None:
    """Constructor rejects window_seconds <= 0."""
    with pytest.raises(ValueError, match="window_seconds"):
        DeviceRateLimiter(max_requests=10, window_seconds=0)


async def test_rate_limiter_rejects_empty_device_id() -> None:
    """check("") raises ValueError."""
    limiter = DeviceRateLimiter(max_requests=10, window_seconds=60)
    with pytest.raises(ValueError, match="device_id"):
        await limiter.check("")


def test_rate_limiter_reset_clears_state() -> None:
    """reset() clears all state (for tests)."""
    limiter = DeviceRateLimiter(max_requests=2, window_seconds=60)
    limiter.reset()
    assert len(limiter._hits) == 0  # type: ignore[attr-defined]


def test_rate_limit_decision_is_frozen() -> None:
    """RateLimitDecision is immutable."""
    decision = RateLimitDecision(allowed=True, remaining=5, reset_seconds=60.0)
    with pytest.raises((AttributeError, Exception)):
        decision.allowed = False  # type: ignore[misc]
