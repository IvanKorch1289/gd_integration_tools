"""Wave 18 (ADR-0391): tag-инвалидация перестала быть no-op.

Дефект 5 (medium): ``CacheInvalidator._backends`` был пуст — ``add_backend()``
в ``src/`` не вызывался нигде → ``invalidate(tag)`` всегда возвращал 0
(проба аудита: ``CacheInvalidator._backends`` == ``[]``).

Цепочка, которую проверяем end-to-end:

    factory → RedisBackend → TenantCacheBackend → CacheInvalidator
    facade.set_ns(..., tags=[...]) → bind_key_to_tag (Redis SET-индекс)
    invalidator.invalidate(tag)   → delete_by_tag (SMEMBERS + DEL)

Redis-клиент — заглушка (без сети).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from src.backend.core.config.services.cache import CacheSettings
from src.backend.infrastructure.cache.factory import create_cache_backend
from src.backend.infrastructure.cache.invalidator import (
    CacheInvalidator,
    get_cache_invalidator,
    set_cache_invalidator,
)
from src.backend.services.cache.facade import UnifiedCacheFacade


class _StubRawRedis:
    """Минимальный raw redis.asyncio.Redis с SET-индексом тегов."""

    def __init__(self) -> None:
        self.store: dict[str, bytes] = {}
        self.sets: dict[str, set[str]] = {}

    async def get(self, key: str) -> bytes | None:
        """GET-заглушка."""
        return self.store.get(key)

    async def set(self, key: str, value: bytes, ex: int | None = None) -> bool:  # noqa: ARG002
        """SET-заглушка."""
        self.store[key] = value
        return True

    async def delete(self, *keys: str) -> int:
        """DEL-заглушка (ключи могут быть bytes — как у реального redis-py)."""
        deleted = 0
        for raw_key in keys:
            key = raw_key.decode() if isinstance(raw_key, bytes) else raw_key
            if self.store.pop(key, None) is not None:
                deleted += 1
            self.sets.pop(key, None)
        return deleted

    async def exists(self, key: str) -> bool:
        """EXISTS-заглушка."""
        return key in self.store

    async def sadd(self, key: str, member: str) -> int:
        """SADD-заглушка (индекс тегов)."""
        members = self.sets.setdefault(key, set())
        members.add(member)
        return len(members)

    async def smembers(self, key: str) -> set[str]:
        """SMEMBERS-заглушка (индекс тегов)."""
        return set(self.sets.get(key, set()))

    async def scan_iter(self, match: str | None = None, count: int | None = None):  # noqa: ARG002
        """SCAN-заглушка (glob-паттерн по ключам)."""
        import fnmatch

        for key in list(self.store):
            if match is None or fnmatch.fnmatch(key, match):
                yield key.encode()


class _StubRedisClient:
    """RedisClient-подобная заглушка с raw-клиентом."""

    def __init__(self, raw: _StubRawRedis) -> None:
        self._raw = raw

    def raw_cache_client(self) -> _StubRawRedis:
        """Возвращает raw-клиент (как ``CacheMixin.raw_cache_client``)."""
        return self._raw


@pytest.fixture(autouse=True)
def _reset_invalidator() -> Any:
    """Изолирует глобальный CacheInvalidator."""
    previous = get_cache_invalidator()
    set_cache_invalidator(CacheInvalidator())
    yield
    set_cache_invalidator(previous)


@pytest.fixture
def raw_redis() -> _StubRawRedis:
    """Заглушка raw redis-клиента."""
    return _StubRawRedis()


@pytest.mark.asyncio
async def test_tag_invalidation_deletes_keys(raw_redis: _StubRawRedis) -> None:
    """``invalidate(tag)`` реально удаляет ключи (а не возвращает 0)."""
    with patch(
        "src.backend.infrastructure.clients.storage.redis.get_redis_client",
        return_value=_StubRedisClient(raw_redis),
    ):
        backend = create_cache_backend(CacheSettings(backend="redis"))

    facade = UnifiedCacheFacade(primary=backend)
    await facade.set_ns("orders:list", b"payload", tags=["entity:orders"])
    await facade.set_ns("users:list", b"payload", tags=["entity:users"])

    removed = await get_cache_invalidator().invalidate("entity:orders")

    assert removed == 1
    assert (await facade.get_ns("orders:list")).hit is False
    assert (await facade.get_ns("users:list")).hit is True


@pytest.mark.asyncio
async def test_pattern_invalidation_deletes_keys(raw_redis: _StubRawRedis) -> None:
    """``invalidate_pattern`` реально удаляет ключи из Redis."""
    with patch(
        "src.backend.infrastructure.clients.storage.redis.get_redis_client",
        return_value=_StubRedisClient(raw_redis),
    ):
        backend = create_cache_backend(CacheSettings(backend="redis"))

    facade = UnifiedCacheFacade(primary=backend)
    await facade.set_ns("orders:list", b"payload")
    await facade.set_ns("users:list", b"payload")

    await get_cache_invalidator().invalidate_pattern("default:orders:*")

    assert (await facade.get_ns("orders:list")).hit is False
    assert (await facade.get_ns("users:list")).hit is True
