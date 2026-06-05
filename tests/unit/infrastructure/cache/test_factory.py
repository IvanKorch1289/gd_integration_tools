"""Unit-tests for cache backend factory."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.backend.core.config.services.cache import CacheSettings
from src.backend.infrastructure.cache.backends.memory import MemoryBackend
from src.backend.infrastructure.cache.backends.redis import RedisBackend
from src.backend.infrastructure.cache.factory import create_cache_backend


class _FakeRedisClient:
    pass


@pytest.fixture
def fake_redis_client(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "src.backend.infrastructure.cache.factory._redis_client",
        lambda: _FakeRedisClient(),
    )


def test_create_memory_backend() -> None:
    settings = CacheSettings(backend="memory", l1_maxsize=128)
    backend = create_cache_backend(settings)
    assert isinstance(backend, MemoryBackend)


def test_create_redis_backend(fake_redis_client: None) -> None:
    settings = CacheSettings(backend="redis")
    backend = create_cache_backend(settings)
    assert isinstance(backend, RedisBackend)


def test_create_keydb_backend(fake_redis_client: None) -> None:
    settings = CacheSettings(backend="keydb", keydb_active_replica=True)
    backend = create_cache_backend(settings)
    from src.backend.infrastructure.cache.backends.keydb import KeyDBBackend

    assert isinstance(backend, KeyDBBackend)


def test_create_memcached_backend_raises_without_aiomcache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(
        "sys.modules", "aiomcache", None
    )
    settings = CacheSettings(backend="memcached")
    with pytest.raises(RuntimeError, match="aiomcache"):
        create_cache_backend(settings)


def test_create_uses_default_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "src.backend.infrastructure.cache.factory.cache_settings",
        CacheSettings(backend="memory", l1_maxsize=256),
    )
    backend = create_cache_backend()
    assert isinstance(backend, MemoryBackend)
