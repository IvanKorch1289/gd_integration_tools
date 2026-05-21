"""Unit-тесты FallbackCache: Redis → cachetools.TTLCache graceful degrade.

Wave: ``[wave:s16/k2-w5-redis-graceful-degrade]``.

Покрытие:
* Get/Set через Redis (golden path) — degraded=False.
* Redis ConnectionError → fallback на TTLCache; degraded=True.
* После повторного успеха Redis → degraded возвращается в False.
* Delete: ловит исключения, удаляет из fallback.
* Multiple failures → counter растёт.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.backend.core.utils.redis_fallback import FallbackCache, RedisLike


class _FakeRedis:
    """Контролируемый Redis-stub для тестов."""

    def __init__(self, *, fail_get: bool = False, fail_set: bool = False) -> None:
        self.store: dict[str, Any] = {}
        self.fail_get = fail_get
        self.fail_set = fail_set
        self.calls: list[tuple[str, ...]] = []

    async def get(self, key: str) -> Any | None:
        self.calls.append(("get", key))
        if self.fail_get:
            raise ConnectionError("redis offline")
        return self.store.get(key)

    async def set(self, key: str, value: Any, ex: int | None = None) -> None:
        self.calls.append(("set", key))
        if self.fail_set:
            raise TimeoutError("redis timeout")
        self.store[key] = value

    async def delete(self, key: str) -> None:
        self.calls.append(("delete", key))
        if self.fail_get:
            raise ConnectionError("redis offline")
        self.store.pop(key, None)


@pytest.mark.asyncio
async def test_get_set_golden_path() -> None:
    """Без сбоев Redis — degraded=False, операции идут через primary."""
    primary = _FakeRedis()
    cache = FallbackCache(primary=primary)
    await cache.set("k1", "v1", ex=30)
    value = await cache.get("k1")
    assert value == "v1"
    assert cache.degraded is False
    assert cache.consecutive_failures == 0


@pytest.mark.asyncio
async def test_get_fallback_on_connection_error() -> None:
    """ConnectionError из Redis → fallback TTLCache; degraded=True."""
    primary = _FakeRedis(fail_get=True)
    cache = FallbackCache(primary=primary)
    # Заранее положим в fallback (имитация прошлого set).
    cache._fallback["k1"] = "fallback-v1"

    value = await cache.get("k1")
    assert value == "fallback-v1"
    assert cache.degraded is True
    assert cache.consecutive_failures == 1


@pytest.mark.asyncio
async def test_set_writes_to_fallback_on_timeout() -> None:
    """TimeoutError при set → запись в fallback; degraded=True."""
    primary = _FakeRedis(fail_set=True)
    cache = FallbackCache(primary=primary)
    await cache.set("k", "v")
    # Через fallback значение читается без обращения к Redis.
    assert cache._fallback.get("k") == "v"
    assert cache.degraded is True


@pytest.mark.asyncio
async def test_recovery_resets_degraded_flag() -> None:
    """После успешного вызова Redis флаг degraded должен сброситься."""
    primary = _FakeRedis(fail_get=True)
    cache = FallbackCache(primary=primary)
    await cache.get("nope")  # degraded → True
    assert cache.degraded is True

    # Восстанавливаем Redis.
    primary.fail_get = False
    primary.store["nope"] = "recovered"
    value = await cache.get("nope")
    assert value == "recovered"
    assert cache.degraded is False
    assert cache.consecutive_failures == 0


@pytest.mark.asyncio
async def test_delete_clears_fallback_too() -> None:
    """delete() удаляет из fallback независимо от Redis-state."""
    primary = _FakeRedis()
    cache = FallbackCache(primary=primary)
    await cache.set("k", "v")
    assert cache._fallback["k"] == "v"
    await cache.delete("k")
    assert cache._fallback.get("k") is None
    assert primary.store.get("k") is None


@pytest.mark.asyncio
async def test_consecutive_failures_count() -> None:
    """Несколько отказов подряд → counter растёт."""
    primary = _FakeRedis(fail_get=True)
    cache = FallbackCache(primary=primary)
    for _ in range(3):
        await cache.get("any")
    assert cache.consecutive_failures == 3


@pytest.mark.asyncio
async def test_reset_degradation_manual() -> None:
    """reset_degradation() сбрасывает degrade-state вручную."""
    primary = _FakeRedis(fail_get=True)
    cache = FallbackCache(primary=primary)
    await cache.get("x")
    assert cache.degraded is True
    cache.reset_degradation()
    assert cache.degraded is False
    assert cache.consecutive_failures == 0


@pytest.mark.asyncio
async def test_fake_redis_implements_protocol() -> None:
    """_FakeRedis структурно соответствует RedisLike Protocol."""
    primary = _FakeRedis()
    assert isinstance(primary, RedisLike)
