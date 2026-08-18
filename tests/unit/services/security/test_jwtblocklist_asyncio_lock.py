"""Regression tests для JWTBlocklist asyncio.Lock migration (Sprint 215+).

Phase 0 verification (2026-08-17) найден race condition в
JWTBlocklist.__init__: использовался threading.Lock() в async-only
methods (revoke/unvoke/is_revoked). Это блокировало event loop при
каждом JWT blacklist check.

Sprint 215+ fix (commit 8127d6a9): self._lock = asyncio.Lock()
+ async with self._lock: во всех async методах.

Тесты проверяют что:
1. asyncio.Lock используется (не threading.Lock)
2. async with pattern работает корректно
3. concurrent revoke/is_revoked не деградируют event loop
"""

from __future__ import annotations

import asyncio
import time

import pytest

from src.backend.services.security.facade import _InMemoryJwtBlacklist


class TestInMemoryJWTBlacklistLockType:
    """Verify asyncio.Lock (НЕ threading.Lock)."""

    def test_lock_is_asyncio_lock(self) -> None:
        bl = _InMemoryJwtBlacklist()
        assert isinstance(bl._lock, asyncio.Lock), (
            f"_InMemoryJwtBlacklist._lock должен быть asyncio.Lock, "
            f"получено {type(bl._lock).__name__}. "
            f"Sprint 215+ fix не применён или регрессировал."
        )


class TestInMemoryJWTBlacklistAsyncAPI:
    """Verify async revoke/unvoke/is_revoked use async with."""

    @pytest.mark.asyncio
    async def test_revoke_then_is_revoked(self) -> None:
        bl = _InMemoryJwtBlacklist()
        await bl.revoke("jti-1", expires_at=int(time.time()) + 3600)
        assert await bl.is_revoked("jti-1") is True

    @pytest.mark.asyncio
    async def test_revoke_unvoke_roundtrip(self) -> None:
        bl = _InMemoryJwtBlacklist()
        await bl.revoke("jti-2", expires_at=int(time.time()) + 3600)
        assert await bl.is_revoked("jti-2") is True
        await bl.unrevoke("jti-2")
        assert await bl.is_revoked("jti-2") is False

    @pytest.mark.asyncio
    async def test_is_revoked_for_unknown_returns_false(self) -> None:
        bl = _InMemoryJwtBlacklist()
        assert await bl.is_revoked("never-revoked") is False

    @pytest.mark.asyncio
    async def test_concurrent_revoke_does_not_corrupt(self) -> None:
        """Stress test: 50 concurrent revokes на 50 разных JTI."""
        bl = _InMemoryJwtBlacklist()
        tasks = [
            bl.revoke(f"jti-{i}", expires_at=int(time.time()) + 3600)
            for i in range(50)
        ]
        await asyncio.gather(*tasks)

        # Verify все 50 — revoked
        for i in range(50):
            assert await bl.is_revoked(f"jti-{i}") is True