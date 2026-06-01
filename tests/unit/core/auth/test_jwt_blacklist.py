"""Unit-тесты :class:`RedisJwtBlacklist` (S18 W4, S-L8-5 batch-revoke).

Покрытие:
    * revoke_before_time устанавливает global barrier (Redis SET без TTL).
    * is_iat_revoked(t) корректно сравнивает iat с barrier (<, ==, >).
    * is_iat_revoked(None) → False (custom JWT без iat не блокируются).
    * is_iat_revoked с не-numeric iat → False (graceful).
    * revoke_before_time идемпотентен с MAX-семантикой (advisor pt 3:
      повторный вызов с меньшим threshold не rollback'ает barrier).
    * Без barrier (Redis пуст) is_iat_revoked → False.
    * Per-jti revoke / is_revoked продолжают работать после S18 W4 расширения.
"""

# ruff: noqa: S101

from __future__ import annotations

import time
from typing import Any

from src.backend.core.auth.jwt_blacklist import RedisJwtBlacklist


class _FakeRedis:
    """In-memory Redis stub: get/set с поддержкой ex= TTL (для unit-теста)."""

    def __init__(self) -> None:
        self.store: dict[str, tuple[bytes, float | None]] = {}

    async def get(self, key: str) -> bytes | None:
        item = self.store.get(key)
        if item is None:
            return None
        value, expires = item
        if expires is not None and expires < time.time():
            self.store.pop(key, None)
            return None
        return value

    async def set(
        self, key: str, value: Any, *, ex: int | None = None
    ) -> None:
        expires = time.time() + ex if ex is not None else None
        if isinstance(value, str):
            value = value.encode()
        self.store[key] = (value, expires)


# ----------------------------- revoke_before_time --------------------------


class TestRevokeBeforeTime:
    """revoke_before_time устанавливает global rotation barrier."""

    async def test_first_call_writes_threshold(self) -> None:
        redis = _FakeRedis()
        blacklist = RedisJwtBlacklist(redis)
        await blacklist.revoke_before_time(1700_000_000)
        # raw value сохранён в Redis под suffix-ключом
        raw = await redis.get("blacklist:jwt:revoke_before")
        assert raw == b"1700000000"

    async def test_subsequent_call_with_higher_threshold_overwrites(
        self,
    ) -> None:
        redis = _FakeRedis()
        blacklist = RedisJwtBlacklist(redis)
        await blacklist.revoke_before_time(1700_000_000)
        await blacklist.revoke_before_time(1800_000_000)
        raw = await redis.get("blacklist:jwt:revoke_before")
        assert raw == b"1800000000"

    async def test_lower_threshold_does_not_rollback(self) -> None:
        """MAX-семантика: меньший threshold НЕ должен откатить barrier."""
        redis = _FakeRedis()
        blacklist = RedisJwtBlacklist(redis)
        await blacklist.revoke_before_time(1800_000_000)
        await blacklist.revoke_before_time(1700_000_000)
        raw = await redis.get("blacklist:jwt:revoke_before")
        assert raw == b"1800000000"


# ----------------------------- is_iat_revoked ------------------------------


class TestIsIatRevoked:
    """is_iat_revoked сравнивает iat с barrier."""

    async def test_no_barrier_returns_false(self) -> None:
        redis = _FakeRedis()
        blacklist = RedisJwtBlacklist(redis)
        # Никакого revoke_before_time не вызвано
        assert await blacklist.is_iat_revoked(1700_000_000) is False

    async def test_iat_before_threshold_returns_true(self) -> None:
        redis = _FakeRedis()
        blacklist = RedisJwtBlacklist(redis)
        await blacklist.revoke_before_time(1750_000_000)
        assert await blacklist.is_iat_revoked(1700_000_000) is True

    async def test_iat_equal_threshold_returns_false(self) -> None:
        """iat == threshold НЕ revoked (strictly less than)."""
        redis = _FakeRedis()
        blacklist = RedisJwtBlacklist(redis)
        await blacklist.revoke_before_time(1750_000_000)
        assert await blacklist.is_iat_revoked(1750_000_000) is False

    async def test_iat_after_threshold_returns_false(self) -> None:
        redis = _FakeRedis()
        blacklist = RedisJwtBlacklist(redis)
        await blacklist.revoke_before_time(1750_000_000)
        assert await blacklist.is_iat_revoked(1800_000_000) is False

    async def test_iat_none_returns_false(self) -> None:
        """Custom JWT без iat не блокируется (advisor pt 3)."""
        redis = _FakeRedis()
        blacklist = RedisJwtBlacklist(redis)
        await blacklist.revoke_before_time(1750_000_000)
        assert await blacklist.is_iat_revoked(None) is False

    async def test_iat_non_numeric_returns_false(self) -> None:
        """Некорректный iat (string без int-cast) → False (graceful)."""
        redis = _FakeRedis()
        blacklist = RedisJwtBlacklist(redis)
        await blacklist.revoke_before_time(1750_000_000)
        assert await blacklist.is_iat_revoked("abc") is False  # type: ignore[arg-type]


# ----------------------------- per-jti backward compat ---------------------


class TestPerJtiUnchanged:
    """S18 W4 не должна сломать существующий per-jti path."""

    async def test_per_jti_revoke_and_check(self) -> None:
        redis = _FakeRedis()
        blacklist = RedisJwtBlacklist(redis)
        await blacklist.revoke("jti-xyz", expires_at=int(time.time()) + 3600)
        assert await blacklist.is_revoked("jti-xyz") is True
        assert await blacklist.is_revoked("absent-jti") is False

    async def test_per_jti_and_batch_independent(self) -> None:
        """is_revoked и is_iat_revoked не интерферируют."""
        redis = _FakeRedis()
        blacklist = RedisJwtBlacklist(redis)
        await blacklist.revoke("jti-1", expires_at=int(time.time()) + 60)
        await blacklist.revoke_before_time(1750_000_000)

        assert await blacklist.is_revoked("jti-1") is True
        assert await blacklist.is_revoked("jti-2") is False
        assert await blacklist.is_iat_revoked(1700_000_000) is True
        assert await blacklist.is_iat_revoked(1800_000_000) is False
