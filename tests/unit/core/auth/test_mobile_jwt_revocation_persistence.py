"""Unit-тесты ``core.auth.mobile_jwt_revocation`` — Sprint C (S50 P0 #31).

S48 swarm audit (A1 Core #1 / A9 Security #3) зафиксировал что
``revocation_store`` параметр в ``build_verifier_with_protections`` ранее
был no-op (Phase 3 deferred). Sprint C verification:
1. ``revocation_store`` IS used (passed to ``_WrappedMobileJwtVerifier.__init__``
   → stored as ``self._revocation_store`` → used in ``is_revoked(ctx.jti)``).
2. Vulture finding (was в BASELINE) — false positive (variable is used
   via constructor).

Sprint C scope: dedicated tests для persistence + revocation lookup
+ rate limiting — establishes coverage baseline для security-critical
``mobile_jwt_revocation.py`` (294 LOC, 0% coverage per BASELINE).
"""

from __future__ import annotations

import time

import pytest

from src.backend.core.auth.mobile_jwt_revocation import (
    DeviceRateLimiter,
    InMemoryRevocationStore,
    RateLimitDecision,
    RevocationError,
    RevocationRecord,
    RevocationStore,
)


@pytest.mark.unit
class TestInMemoryRevocationStore:
    """``InMemoryRevocationStore`` — protocol implementation."""

    @pytest.mark.asyncio
    async def test_revoke_persists_jti(self) -> None:
        """``revoke(jti, expires_at)`` → ``is_revoked(jti)`` returns True."""
        store = InMemoryRevocationStore()
        expires = time.time() + 3600
        await store.revoke(jti="test-jti", expires_at=expires)
        assert await store.is_revoked(jti="test-jti") is True

    @pytest.mark.asyncio
    async def test_is_revoked_returns_false_for_unknown_jti(self) -> None:
        """``is_revoked(unknown)`` → False (never revoked)."""
        store = InMemoryRevocationStore()
        assert await store.is_revoked(jti="never-revoked") is False

    @pytest.mark.asyncio
    async def test_revoke_empty_jti_raises_value_error(self) -> None:
        """``revoke(jti="")`` → ``ValueError`` (jti must be non-empty)."""
        store = InMemoryRevocationStore()
        with pytest.raises(ValueError, match="non-empty"):
            await store.revoke(jti="", expires_at=time.time() + 3600)

    @pytest.mark.asyncio
    async def test_revoke_past_expiry_raises_value_error(self) -> None:
        """``revoke(expires_at=past)`` → ``ValueError`` (must be future)."""
        store = InMemoryRevocationStore()
        with pytest.raises(ValueError, match="future"):
            await store.revoke(jti="x", expires_at=time.time() - 1)

    @pytest.mark.asyncio
    async def test_is_revoked_auto_expires(self) -> None:
        """``is_revoked(expired)`` → False (auto-popup на expiry)."""
        store = InMemoryRevocationStore()
        # Expire в прошлом — auto-expire на is_revoked
        await store.revoke(jti="test", expires_at=time.time() + 1)
        # time.sleep не нужен — _revoked.pop triggered по time.time() check.
        # Wait briefly to ensure expiry:
        time.sleep(1.1)
        assert await store.is_revoked(jti="test") is False

    @pytest.mark.asyncio
    async def test_multiple_revocations_accumulate(self) -> None:
        """Множественные revocations → store accumulates (not overwrites)."""
        store = InMemoryRevocationStore()
        expires = time.time() + 3600
        for jti in ["jti-a", "jti-b", "jti-c"]:
            await store.revoke(jti=jti, expires_at=expires)
        assert len(store) == 3
        assert await store.is_revoked(jti="jti-a") is True
        assert await store.is_revoked(jti="jti-b") is True
        assert await store.is_revoked(jti="jti-c") is True

    @pytest.mark.asyncio
    async def test_cleanup_expired_removes_only_expired(self) -> None:
        """``cleanup_expired()`` удаляет только expired (не valid)."""
        store = InMemoryRevocationStore()
        now = time.time()
        # 1 valid (через revoke) + 1 expired (через dict bypass — revoke
        # запрещает past expires_at per design)
        await store.revoke(jti="valid", expires_at=now + 3600)
        store._revoked["expired"] = RevocationRecord(
            jti="expired", revoked_at=now - 100, expires_at=now - 1
        )
        # Cleanup expired (valid still active):
        removed = await store.cleanup_expired()
        assert removed == 1
        assert len(store) == 1
        assert await store.is_revoked(jti="valid") is True

    @pytest.mark.asyncio
    async def test_revoke_same_jti_twice_overwrites(self) -> None:
        """``revoke(jti, new_expires_at)`` для существующего jti → overwrites."""
        store = InMemoryRevocationStore()
        await store.revoke(jti="dup", expires_at=time.time() + 100)
        # New expiration — overwrite
        await store.revoke(jti="dup", expires_at=time.time() + 3600)
        assert len(store) == 1
        assert await store.is_revoked(jti="dup") is True


@pytest.mark.unit
class TestDeviceRateLimiter:
    """``DeviceRateLimiter`` — sliding window."""

    @pytest.mark.asyncio
    async def test_first_request_allowed(self) -> None:
        """Первый request → allowed=True, remaining=N-1."""
        limiter = DeviceRateLimiter(max_requests=3, window_seconds=60)
        decision = await limiter.check(device_id="device-1")
        assert decision.allowed is True
        assert decision.remaining == 2

    @pytest.mark.asyncio
    async def test_max_requests_then_rejected(self) -> None:
        """N+1 request → rejected (allowed=False, remaining=0)."""
        limiter = DeviceRateLimiter(max_requests=2, window_seconds=60)
        d1 = await limiter.check(device_id="dev")
        d2 = await limiter.check(device_id="dev")
        d3 = await limiter.check(device_id="dev")
        assert d1.allowed is True
        assert d2.allowed is True
        assert d3.allowed is False
        assert d3.remaining == 0

    @pytest.mark.asyncio
    async def test_per_device_independent(self) -> None:
        """``check(device_a)`` НЕ влияет на ``check(device_b)``."""
        limiter = DeviceRateLimiter(max_requests=1, window_seconds=60)
        d_a1 = await limiter.check(device_id="A")
        d_b1 = await limiter.check(device_id="B")
        d_a2 = await limiter.check(device_id="A")
        assert d_a1.allowed is True
        assert d_b1.allowed is True
        assert d_a2.allowed is False  # A exceeded

    @pytest.mark.asyncio
    async def test_empty_device_id_raises_value_error(self) -> None:
        """``check(device_id="")`` → ValueError."""
        limiter = DeviceRateLimiter(max_requests=1, window_seconds=60)
        with pytest.raises(ValueError, match="non-empty"):
            await limiter.check(device_id="")

    def test_invalid_max_requests_raises(self) -> None:
        """``max_requests <= 0`` → ValueError."""
        with pytest.raises(ValueError, match="max_requests"):
            DeviceRateLimiter(max_requests=0, window_seconds=60)

    def test_invalid_window_seconds_raises(self) -> None:
        """``window_seconds <= 0`` → ValueError."""
        with pytest.raises(ValueError, match="window_seconds"):
            DeviceRateLimiter(max_requests=10, window_seconds=0)

    def test_reset_clears_all(self) -> None:
        """``reset(None)`` очищает state всех devices."""
        limiter = DeviceRateLimiter(max_requests=1, window_seconds=60)
        limiter._hits["dev-1"] = [time.time()]
        limiter._hits["dev-2"] = [time.time()]
        limiter.reset()
        assert limiter._hits == {}

    def test_reset_specific_device(self) -> None:
        """``reset(device_id)`` очищает только specified device."""
        limiter = DeviceRateLimiter(max_requests=1, window_seconds=60)
        limiter._hits["dev-1"] = [time.time()]
        limiter._hits["dev-2"] = [time.time()]
        limiter.reset("dev-1")
        assert "dev-1" not in limiter._hits
        assert "dev-2" in limiter._hits


@pytest.mark.unit
class TestRevocationStoreProtocol:
    """``RevocationStore`` Protocol — structural subtyping check."""

    def test_in_memory_store_satisfies_protocol(self) -> None:
        """``InMemoryRevocationStore`` structurally satisfies ``RevocationStore``."""
        # Protocol classes have ``__subclasshook__`` — runtime_checkable.
        assert hasattr(RevocationStore, "__subclasshook__")
        # InMemoryRevocationStore must have all 3 methods.
        store = InMemoryRevocationStore()
        assert hasattr(store, "is_revoked")
        assert hasattr(store, "revoke")
        assert hasattr(store, "cleanup_expired")


@pytest.mark.unit
class TestBuildVerifierWithProtections:
    """``build_verifier_with_protections`` — integration glue."""

    def test_no_stores_returns_bare_verifier(self) -> None:
        """Без stores → ``MobileJwtVerifier`` (no wrapping)."""
        from src.backend.core.auth.mobile_jwt import MobileJwtVerifier
        from src.backend.core.auth.mobile_jwt_revocation import (
            build_verifier_with_protections,
        )

        class _FakeBackend:
            pass

        verifier = build_verifier_with_protections(
            backend=_FakeBackend(),
            issuer_whitelist=["test"],
            audience="test",
        )
        assert isinstance(verifier, MobileJwtVerifier)

    def test_with_revocation_store_returns_wrapped(self) -> None:
        """С ``revocation_store`` → ``_WrappedMobileJwtVerifier``."""
        from src.backend.core.auth.mobile_jwt_revocation import (
            _WrappedMobileJwtVerifier,
            build_verifier_with_protections,
        )

        class _FakeBackend:
            pass

        verifier = build_verifier_with_protections(
            backend=_FakeBackend(),
            issuer_whitelist=["test"],
            audience="test",
            revocation_store=InMemoryRevocationStore(),
        )
        assert isinstance(verifier, _WrappedMobileJwtVerifier)


# Sanity check: RevocationRecord is frozen dataclass (immutable)

@pytest.mark.unit
class TestRevocationRecord:
    """``RevocationRecord`` — frozen dataclass."""

    def test_frozen(self) -> None:
        """``RevocationRecord`` frozen — mutation raises."""
        record = RevocationRecord(
            jti="x", revoked_at=time.time(), expires_at=time.time() + 3600
        )
        with pytest.raises((AttributeError, TypeError, Exception)):  # noqa: B017
            record.jti = "y"  # type: ignore[misc]

    def test_equality_via_dataclass(self) -> None:
        """``__eq__`` auto-generated by dataclass (same fields → equal)."""
        now = time.time()
        a = RevocationRecord(jti="x", revoked_at=now, expires_at=now + 3600)
        b = RevocationRecord(jti="x", revoked_at=now, expires_at=now + 3600)
        assert a == b


# Sanity check: RevocationError is Exception subclass

def test_revocation_error_is_exception() -> None:
    """``RevocationError`` — Exception subclass."""
    assert issubclass(RevocationError, Exception)


def test_rate_limit_decision_is_dataclass() -> None:
    """``RateLimitDecision`` — dataclass with allowed/remaining/reset_seconds."""
    decision = RateLimitDecision(allowed=True, remaining=5, reset_seconds=60.0)
    assert decision.allowed is True
    assert decision.remaining == 5
    assert decision.reset_seconds == 60.0
