# ruff: noqa: S101
"""Unit tests for cache backend factory (infrastructure/cache/factory.py).

Covers all 4 backend modes (memory/redis/keydb/memcached) + error paths:
- _redis_client() RuntimeError if not initialized
- memcached backend raises RuntimeError if aiomcache missing
- default settings (no arg) uses cache_settings singleton
- keydb_active_replica passed through to KeyDBBackend
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

from src.backend.core.config.services.cache import CacheSettings
from src.backend.infrastructure.cache import factory
from src.backend.infrastructure.cache.factory import create_cache_backend

# ── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture
def cfg_memory() -> CacheSettings:
    """CacheSettings with memory backend."""
    return CacheSettings(backend="memory", l1_maxsize=256)


@pytest.fixture
def cfg_redis() -> CacheSettings:
    """CacheSettings with redis backend."""
    return CacheSettings(backend="redis")


@pytest.fixture
def cfg_keydb() -> CacheSettings:
    """CacheSettings with keydb backend (default active_replica=False)."""
    return CacheSettings(backend="keydb", keydb_active_replica=True)


@pytest.fixture
def cfg_keydb_no_replica() -> CacheSettings:
    """CacheSettings with keydb backend and active_replica=False."""
    return CacheSettings(backend="keydb", keydb_active_replica=False)


@pytest.fixture
def cfg_memcached() -> CacheSettings:
    """CacheSettings with memcached backend."""
    return CacheSettings(backend="memcached")


# ── memory backend ─────────────────────────────────────────────────


def test_memory_backend(cfg_memory: CacheSettings) -> None:
    """backend=memory → MemoryBackend with correct maxsize."""
    with patch.object(factory, "MemoryBackend") as mock_mem:
        result = create_cache_backend(cfg_memory)
        mock_mem.assert_called_once_with(maxsize=256)
        assert result is mock_mem.return_value


def test_memory_backend_default_l1_maxsize() -> None:
    """MemoryBackend receives l1_maxsize from settings (default 1000)."""
    cfg = CacheSettings(backend="memory")  # default l1_maxsize=1000
    with patch.object(factory, "MemoryBackend") as mock_mem:
        create_cache_backend(cfg)
        mock_mem.assert_called_once_with(maxsize=1000)


# ── redis backend ──────────────────────────────────────────────────


def test_redis_backend_uses_raw_client(cfg_redis: CacheSettings) -> None:
    """backend=redis → RedisBackend(client=_redis_client())."""
    fake_redis_client = MagicMock(name="raw_redis")
    with (
        patch.object(factory, "RedisBackend") as mock_redis,
        patch.object(factory, "_redis_client", return_value=fake_redis_client),
    ):
        result = create_cache_backend(cfg_redis)
        mock_redis.assert_called_once_with(client=fake_redis_client)
        assert result is mock_redis.return_value


# ── keydb backend ──────────────────────────────────────────────────


def test_keydb_backend_with_active_replica(cfg_keydb: CacheSettings) -> None:
    """backend=keydb + keydb_active_replica=True → KeyDBBackend with flag."""
    fake_redis_client = MagicMock(name="raw_redis")
    with (
        patch.object(factory, "KeyDBBackend") as mock_keydb,
        patch.object(factory, "_redis_client", return_value=fake_redis_client),
    ):
        result = create_cache_backend(cfg_keydb)
        mock_keydb.assert_called_once_with(
            client=fake_redis_client, active_replica=True
        )
        assert result is mock_keydb.return_value


def test_keydb_backend_without_active_replica(
    cfg_keydb_no_replica: CacheSettings,
) -> None:
    """backend=keydb + keydb_active_replica=False → flag passed as False."""
    fake_redis_client = MagicMock(name="raw_redis")
    with (
        patch.object(factory, "KeyDBBackend") as mock_keydb,
        patch.object(factory, "_redis_client", return_value=fake_redis_client),
    ):
        create_cache_backend(cfg_keydb_no_replica)
        mock_keydb.assert_called_once_with(
            client=fake_redis_client, active_replica=False
        )


# ── memcached backend ──────────────────────────────────────────────


def test_memcached_backend_success(cfg_memcached: CacheSettings) -> None:
    """backend=memcached + aiomcache available → MemcachedBackend()."""
    # Inject fake aiomcache into sys.modules (factory does `import aiomcache`)
    fake_aiomcache = MagicMock(name="aiomcache_module")
    with (
        patch.dict(sys.modules, {"aiomcache": fake_aiomcache}),
        patch.object(factory, "MemcachedBackend") as mock_memcached,
    ):
        result = create_cache_backend(cfg_memcached)
        # Import succeeded, MemcachedBackend instantiated
        mock_memcached.assert_called_once_with()
        assert result is mock_memcached.return_value


def test_memcached_backend_raises_when_aiomcache_missing(
    cfg_memcached: CacheSettings,
) -> None:
    """backend=memcached + aiomcache MISSING → RuntimeError with hint."""
    # Ensure aiomcache is NOT in sys.modules
    saved = sys.modules.pop("aiomcache", None)
    # Block the import (factory does `import aiomcache` inline)
    with patch.dict(sys.modules, {"aiomcache": None}):
        with pytest.raises(RuntimeError, match="aiomcache"):
            create_cache_backend(cfg_memcached)
    if saved is not None:
        sys.modules["aiomcache"] = saved


def test_memcached_runtime_error_message_helpful(cfg_memcached: CacheSettings) -> None:
    """RuntimeError message includes 'aiomcache' and 'pyproject.toml' hints."""
    saved = sys.modules.pop("aiomcache", None)
    with patch.dict(sys.modules, {"aiomcache": None}):
        with pytest.raises(RuntimeError) as exc_info:
            create_cache_backend(cfg_memcached)
        msg = str(exc_info.value)
        assert "aiomcache" in msg
        assert "pyproject.toml" in msg
    if saved is not None:
        sys.modules["aiomcache"] = saved


# ── _redis_client helper ───────────────────────────────────────────


def test_redis_client_uses_raw_client_attribute() -> None:
    """_redis_client prefers _raw_client attribute on redis_client singleton."""
    fake_raw = MagicMock(name="raw_redis")
    fake_singleton = MagicMock(spec=["_raw_client"])
    fake_singleton._raw_client = fake_raw
    with patch(
        "src.backend.infrastructure.clients.storage.redis.redis_client", fake_singleton
    ):
        result = factory._redis_client()
    assert result is fake_raw


def test_redis_client_falls_back_to_client_attribute() -> None:
    """_redis_client falls back to .client attribute if no _raw_client."""
    fake_raw = MagicMock(name="raw_redis")
    fake_singleton = MagicMock(spec=["client"])
    fake_singleton._raw_client = None  # first lookup yields None
    fake_singleton.client = fake_raw
    with patch(
        "src.backend.infrastructure.clients.storage.redis.redis_client", fake_singleton
    ):
        result = factory._redis_client()
    assert result is fake_raw


def test_redis_client_raises_if_not_initialized() -> None:
    """_redis_client raises RuntimeError if neither _raw_client nor client set."""
    fake_singleton = MagicMock(spec=[])  # no attributes
    with patch(
        "src.backend.infrastructure.clients.storage.redis.redis_client", fake_singleton
    ):
        with pytest.raises(RuntimeError, match="redis_client не инициализирован"):
            factory._redis_client()


# ── default settings (no arg) ──────────────────────────────────────


def test_no_settings_uses_singleton() -> None:
    """create_cache_backend() with no arg uses cache_settings singleton."""
    with patch.object(factory, "MemoryBackend") as mock_mem:
        # default cache_settings has backend=redis, override via cache_settings
        with patch.object(factory, "cache_settings", backend="memory"):
            result = create_cache_backend()
        mock_mem.assert_called_once()
        assert result is mock_mem.return_value


# ── logger name (smoke) ─────────────────────────────────────────────


def test_module_logger() -> None:
    """Module has a logger named 'infrastructure.cache.factory'."""
    assert factory.logger.name == "infrastructure.cache.factory"
