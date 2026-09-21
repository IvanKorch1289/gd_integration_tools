"""Focused tests for ``core.rate_limiter`` (Wave 4 P2.14b)."""

from __future__ import annotations

import time

import pytest

from src.backend.core.rate_limiter import (
    AsyncRateLimiter,
    RateLimiter,
    RateLimiterConfig,
    get_rate_limiter,
)
from src.backend.core.rate_limiter.limiter import reset_rate_limiters


@pytest.fixture(autouse=True)
def _reset() -> None:
    reset_rate_limiters()


class TestRateLimiterConfig:
    def test_defaults(self) -> None:
        c = RateLimiterConfig()
        assert c.max_tokens == 10
        assert c.refill_rate == 1.0
        assert c.initial_tokens == 10

    def test_custom(self) -> None:
        c = RateLimiterConfig(max_tokens=100, refill_rate=5.0)
        assert c.max_tokens == 100

    def test_validate_max_tokens_positive(self) -> None:
        with pytest.raises(ValueError, match="max_tokens"):
            RateLimiterConfig(max_tokens=0)

    def test_validate_refill_rate_positive(self) -> None:
        with pytest.raises(ValueError, match="refill_rate"):
            RateLimiterConfig(refill_rate=0)

    def test_validate_initial_tokens_in_range(self) -> None:
        with pytest.raises(ValueError, match="initial_tokens"):
            RateLimiterConfig(max_tokens=10, initial_tokens=20)


class TestRateLimiterSync:
    def test_init_full_tokens(self) -> None:
        rl = RateLimiter(RateLimiterConfig(max_tokens=10))
        assert rl.available_tokens == 10.0

    def test_init_partial_tokens(self) -> None:
        rl = RateLimiter(
            RateLimiterConfig(max_tokens=10, initial_tokens=3)
        )
        assert rl.available_tokens == 3.0

    def test_try_acquire_decrements(self) -> None:
        rl = RateLimiter(RateLimiterConfig(max_tokens=5, initial_tokens=5))
        assert rl.try_acquire() is True
        assert rl.available_tokens == 4.0

    def test_try_acquire_fails_when_empty(self) -> None:
        rl = RateLimiter(
            RateLimiterConfig(max_tokens=2, initial_tokens=0, refill_rate=0.1)
        )
        assert rl.try_acquire() is False
        # Allow tiny refilled amount (sub-1.0 for rate 0.1 over <1s).
        assert rl.available_tokens < 1.0

    def test_refill_over_time(self) -> None:
        rl = RateLimiter(
            RateLimiterConfig(max_tokens=10, initial_tokens=0, refill_rate=10.0)
        )
        # Refill happens on next try_acquire call.
        time.sleep(0.5)
        assert rl.try_acquire() is True
        # Should have ~5 tokens refilled.
        assert rl.available_tokens >= 4.0

    def test_refill_caps_at_max(self) -> None:
        rl = RateLimiter(
            RateLimiterConfig(max_tokens=5, initial_tokens=5, refill_rate=100.0)
        )
        time.sleep(0.1)
        # Should still cap at max_tokens.
        assert rl.available_tokens == 5.0

    def test_try_acquire_custom_cost(self) -> None:
        rl = RateLimiter(
            RateLimiterConfig(max_tokens=10, initial_tokens=10)
        )
        assert rl.try_acquire(cost=3.0) is True
        assert rl.available_tokens == 7.0

    def test_try_acquire_insufficient_tokens(self) -> None:
        rl = RateLimiter(
            RateLimiterConfig(max_tokens=10, initial_tokens=2)
        )
        assert rl.try_acquire(cost=5.0) is False

    def test_reset(self) -> None:
        rl = RateLimiter(
            RateLimiterConfig(max_tokens=10, initial_tokens=10, refill_rate=0.1)
        )
        # Consume a token.
        rl._tokens = 5.0
        rl.reset()
        assert rl.available_tokens == 10.0


class TestRateLimiterSyncAcquire:
    def test_acquire_immediate(self) -> None:
        rl = RateLimiter(
            RateLimiterConfig(max_tokens=5, initial_tokens=5, refill_rate=1.0)
        )
        assert rl.acquire() is True

    def test_acquire_with_timeout_fails(self) -> None:
        rl = RateLimiter(
            RateLimiterConfig(
                max_tokens=1, initial_tokens=0, refill_rate=0.0001
            )
        )
        # Acquire 1 token (refill needs 10000s, so this is only via reset).
        # We don't acquire; just verify timeout works on empty bucket.
        start = time.monotonic()
        assert rl.acquire(timeout=0.1) is False
        elapsed = time.monotonic() - start
        assert elapsed < 0.5

    def test_acquire_eventually_succeeds(self) -> None:
        rl = RateLimiter(
            RateLimiterConfig(
                max_tokens=1, initial_tokens=0, refill_rate=10.0
            )
        )
        # Should refill within 0.5s.
        start = time.monotonic()
        assert rl.acquire(timeout=1.0) is True
        elapsed = time.monotonic() - start
        assert elapsed < 0.5  # Got token via refill.


class TestAsyncRateLimiter:
    def test_init_full(self) -> None:
        arl = AsyncRateLimiter(RateLimiterConfig(max_tokens=5))
        assert arl.available_tokens == 5.0

    async def test_try_acquire_decrements(self) -> None:
        arl = AsyncRateLimiter(
            RateLimiterConfig(max_tokens=5, initial_tokens=5)
        )
        assert await arl.try_acquire() is True
        assert arl.available_tokens == 4.0

    async def test_try_acquire_fails(self) -> None:
        arl = AsyncRateLimiter(
            RateLimiterConfig(max_tokens=2, initial_tokens=0, refill_rate=0.1)
        )
        assert await arl.try_acquire() is False

    async def test_acquire_eventually(self) -> None:
        arl = AsyncRateLimiter(
            RateLimiterConfig(
                max_tokens=1, initial_tokens=0, refill_rate=20.0
            )
        )
        assert await arl.acquire(timeout=0.5) is True

    async def test_acquire_timeout(self) -> None:
        arl = AsyncRateLimiter(
            RateLimiterConfig(
                max_tokens=1, initial_tokens=0, refill_rate=0.001
            )
        )
        # First acquire to consume the (empty) bucket — no token.
        # Now try with timeout.
        assert await arl.acquire(timeout=0.2) is False


class TestGetRateLimiter:
    def test_singleton(self) -> None:
        rl1 = get_rate_limiter("test1")
        rl2 = get_rate_limiter("test1")
        assert rl1 is rl2

    def test_different_names(self) -> None:
        rl1 = get_rate_limiter("a")
        rl2 = get_rate_limiter("b")
        assert rl1 is not rl2

    def test_with_config(self) -> None:
        rl = get_rate_limiter(
            "configured",
            RateLimiterConfig(max_tokens=20),
        )
        assert rl.available_tokens == 20.0


class TestExports:
    def test_module_all(self) -> None:
        from src.backend.core import rate_limiter

        assert rate_limiter.__all__ == (
            "AsyncRateLimiter",
            "RateLimiter",
            "RateLimiterConfig",
            "get_rate_limiter",
        )


class TestRealisticExample:
    """Realistic: protect external API (e.g., SKB)."""

    def test_protect_skb_api(self) -> None:
        """Token bucket for SKB API: 10 requests per second burst."""
        skb_limiter = get_rate_limiter(
            "skb_api",
            RateLimiterConfig(max_tokens=10, refill_rate=2.0),
        )

        # Burst: 10 calls succeed immediately.
        for i in range(10):
            assert skb_limiter.try_acquire() is True, f"Call {i+1} should pass"

        # 11th call fails (bucket empty).
        assert skb_limiter.try_acquire() is False

        # After 1 second, 2 tokens refilled.
        time.sleep(1.0)
        assert skb_limiter.try_acquire() is True
        assert skb_limiter.try_acquire() is True
        # 3rd call fails.
        assert skb_limiter.try_acquire() is False
