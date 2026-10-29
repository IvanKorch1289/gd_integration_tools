"""Wave 18 (ADR-0391): фабрика кэш-бэкендов обязана отдавать raw redis-клиент.

Регрессия (дефект 1, critical): ``_redis_client()`` брал
``getattr(client, "_raw_client", None) or getattr(client, "client", None)``.
У ``RedisClient`` нет ``_raw_client``, а property ``client`` возвращает
``self`` → в ``RedisBackend`` попадала обёртка → ``AttributeError:
'RedisClient' object has no attribute 'get'`` → Redis НЕ использовался
вообще (кэш = только per-process L1, в k8s — 100% miss).

Тесты используют заглушку raw redis-клиента — сеть не нужна.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from src.backend.core.config.services.cache import CacheSettings
from src.backend.infrastructure.cache import factory
from src.backend.infrastructure.cache.factory import create_cache_backend
from src.backend.infrastructure.cache.invalidator import (
    CacheInvalidator,
    get_cache_invalidator,
    set_cache_invalidator,
)
from src.backend.infrastructure.cache.tenant_wrapper import TenantCacheBackend
from src.backend.infrastructure.clients.storage.redis import cache_mixin as cm_mod


class _StubRawRedis:
    """Минимальный raw ``redis.asyncio.Redis`` — in-memory, без сети."""

    def __init__(self) -> None:
        self.store: dict[str, bytes] = {}

    async def get(self, key: str) -> bytes | None:
        """GET-заглушка."""
        return self.store.get(key)

    async def set(self, key: str, value: bytes, ex: int | None = None) -> bool:  # noqa: ARG002
        """SET-заглушка."""
        self.store[key] = value
        return True

    async def delete(self, *keys: str) -> int:
        """DEL-заглушка."""
        deleted = 0
        for key in keys:
            if self.store.pop(key, None) is not None:
                deleted += 1
        return deleted

    async def exists(self, key: str) -> bool:
        """EXISTS-заглушка."""
        return key in self.store


class _StubRedisClient(cm_mod.CacheMixin):
    """``RedisClient``-подобный объект с реальной реализацией ``raw_cache_client``.

    Используется ``CacheMixin.raw_cache_client`` (боевой код), но
    ``_build_client`` подменён — сеть не нужна.
    """

    def __init__(self, raw: _StubRawRedis) -> None:
        self._clients: dict[str, Any] = {"cache": None, "queue": None, "limits": None}
        self._raw = raw
        self.logger = factory.logger

    def _build_client(self, kind: str) -> Any:  # noqa: ARG002
        """Возвращает заглушку raw-клиента вместо сетевого redis.asyncio.Redis."""
        return self._raw


@pytest.fixture(autouse=True)
def _reset_invalidator() -> Any:
    """Изолирует глобальный CacheInvalidator между тестами."""
    previous = get_cache_invalidator()
    set_cache_invalidator(CacheInvalidator())
    yield
    set_cache_invalidator(previous)


@pytest.fixture
def raw_redis() -> _StubRawRedis:
    """Заглушка raw redis-клиента."""
    return _StubRawRedis()


@pytest.fixture
def stub_redis_client(raw_redis: _StubRawRedis) -> _StubRedisClient:
    """Заглушка RedisClient с raw-клиентом."""
    return _StubRedisClient(raw_redis)


@pytest.mark.unit
def test_factory_passes_raw_client_to_redis_backend(
    stub_redis_client: _StubRedisClient, raw_redis: _StubRawRedis
) -> None:
    """В RedisBackend попадает raw redis-клиент, а НЕ обёртка RedisClient."""
    with patch(
        "src.backend.infrastructure.clients.storage.redis.get_redis_client",
        return_value=stub_redis_client,
    ):
        backend = create_cache_backend(CacheSettings(backend="redis"))

    assert isinstance(backend, TenantCacheBackend)
    inner = backend.wrapped
    assert getattr(inner, "_client") is raw_redis, (
        "RedisBackend должен получать raw redis.asyncio.Redis, "
        f"а не {type(getattr(inner, '_client')).__name__}"
    )
    assert not isinstance(getattr(inner, "_client"), _StubRedisClient)


@pytest.mark.asyncio
async def test_factory_backend_get_set_roundtrip(
    stub_redis_client: _StubRedisClient, raw_redis: _StubRawRedis
) -> None:
    """Фабрика → RedisBackend → raw redis-клиент: get/set работают."""
    with patch(
        "src.backend.infrastructure.clients.storage.redis.get_redis_client",
        return_value=stub_redis_client,
    ):
        backend = create_cache_backend(CacheSettings(backend="redis"))

    await backend.set("k1", b"v1", 60)
    assert await backend.get("k1") == b"v1"
    assert raw_redis.store, "значение должно попасть в raw redis-клиент"
    assert list(raw_redis.store.values()) == [b"v1"]

    await backend.delete("k1")
    assert await backend.get("k1") is None


@pytest.mark.asyncio
async def test_raw_cache_client_creates_client_lazily(
    stub_redis_client: _StubRedisClient, raw_redis: _StubRawRedis
) -> None:
    """``raw_cache_client()`` создаёт клиент без сетевого I/O и кэширует его."""
    assert stub_redis_client._clients["cache"] is None

    first = stub_redis_client.raw_cache_client()
    second = stub_redis_client.raw_cache_client()

    assert first is raw_redis
    assert second is raw_redis
    assert stub_redis_client._clients["cache"] is raw_redis


@pytest.mark.unit
def test_redis_client_helper_rejects_wrapper_client() -> None:
    """Обёртка (``client`` → self) больше не принимается как raw-клиент."""

    class _Wrapper:
        """Имитация старого RedisClient: ``client`` возвращает self."""

        @property
        def client(self) -> Any:
            """Self-reference (legacy backward-compat)."""
            return self

    with patch(
        "src.backend.infrastructure.clients.storage.redis.get_redis_client",
        return_value=_Wrapper(),
    ):
        with pytest.raises(RuntimeError, match="redis_client не инициализирован"):
            factory._redis_client()


@pytest.mark.unit
def test_factory_registers_backend_in_cache_invalidator(
    stub_redis_client: _StubRedisClient,
) -> None:
    """Фабрика регистрирует backend в глобальном CacheInvalidator (дефект 5)."""
    with patch(
        "src.backend.infrastructure.clients.storage.redis.get_redis_client",
        return_value=stub_redis_client,
    ):
        backend = create_cache_backend(CacheSettings(backend="redis"))

    invalidator = get_cache_invalidator()
    assert invalidator.backends, "CacheInvalidator._backends не должен быть пустым"
    assert backend in invalidator.backends


@pytest.mark.unit
def test_factory_registers_backend_only_once(
    stub_redis_client: _StubRedisClient,
) -> None:
    """Повторная регистрация того же backend'а не дублирует запись."""
    with patch(
        "src.backend.infrastructure.clients.storage.redis.get_redis_client",
        return_value=stub_redis_client,
    ):
        backend = create_cache_backend(CacheSettings(backend="redis"))
        create_cache_backend(CacheSettings(backend="redis"))

    invalidator = get_cache_invalidator()
    assert invalidator.backends.count(backend) == 1
