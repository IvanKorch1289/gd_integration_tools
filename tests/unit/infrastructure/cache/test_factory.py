# ruff: noqa: S101
"""Unit tests for cache backend factory (infrastructure/cache/factory.py).

Covers all 4 backend modes (memory/redis/keydb/memcached) + error paths:
- _redis_client() RuntimeError if not initialized
- memcached backend raises RuntimeError if aiomcache missing
- default settings (no arg) uses cache_settings singleton
- keydb_active_replica passed through to KeyDBBackend
- B-03 fix (cycle 34): returned backend wrapped in TenantCacheBackend
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

from src.backend.core.config.services.cache import CacheSettings
from src.backend.infrastructure.cache import factory
from src.backend.infrastructure.cache.factory import create_cache_backend
from src.backend.infrastructure.cache.tenant_wrapper import TenantCacheBackend

# ── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _disable_tenant_cache_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    """Cycle 34 B-03: existing tests assume plain backend (no tenant prefix).

    Feature flag default = True (production). For factory tests that
    только verify backend construction (not tenant namespacing), мы
    выключаем prefix — wrapper остаётся, но ``_prefix()`` возвращает
    ``""`` (no-op).
    """
    from src.backend.core.config.features import feature_flags

    monkeypatch.setattr(feature_flags, "tenant_cache_prefix_enabled", False)


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
    """backend=memory → MemoryBackend with correct maxsize (wrapped in TenantCacheBackend)."""
    with patch.object(factory, "MemoryBackend") as mock_mem:
        result = create_cache_backend(cfg_memory)
        mock_mem.assert_called_once_with(maxsize=256)
        # B-03: возвращённый backend обёрнут в TenantCacheBackend.
        assert isinstance(result, TenantCacheBackend)
        assert result.wrapped is mock_mem.return_value


def test_memory_backend_default_l1_maxsize() -> None:
    """MemoryBackend receives l1_maxsize from settings (default 1000)."""
    cfg = CacheSettings(backend="memory")  # default l1_maxsize=1000
    with patch.object(factory, "MemoryBackend") as mock_mem:
        create_cache_backend(cfg)
        mock_mem.assert_called_once_with(maxsize=1000)


# ── redis backend ──────────────────────────────────────────────────


def test_redis_backend_uses_raw_client(cfg_redis: CacheSettings) -> None:
    """backend=redis → RedisBackend(client=_redis_client()) (wrapped)."""
    fake_redis_client = MagicMock(name="raw_redis")
    with (
        patch.object(factory, "RedisBackend") as mock_redis,
        patch.object(factory, "_redis_client", return_value=fake_redis_client),
    ):
        result = create_cache_backend(cfg_redis)
        mock_redis.assert_called_once_with(client=fake_redis_client)
        # B-03: возвращённый backend обёрнут в TenantCacheBackend.
        assert isinstance(result, TenantCacheBackend)
        assert result.wrapped is mock_redis.return_value


# ── keydb backend ──────────────────────────────────────────────────


def test_keydb_backend_with_active_replica(cfg_keydb: CacheSettings) -> None:
    """backend=keydb + keydb_active_replica=True → KeyDBBackend (wrapped)."""
    fake_redis_client = MagicMock(name="raw_redis")
    with (
        patch.object(factory, "KeyDBBackend") as mock_keydb,
        patch.object(factory, "_redis_client", return_value=fake_redis_client),
    ):
        result = create_cache_backend(cfg_keydb)
        mock_keydb.assert_called_once_with(
            client=fake_redis_client, active_replica=True
        )
        # B-03: возвращённый backend обёрнут в TenantCacheBackend.
        assert isinstance(result, TenantCacheBackend)
        assert result.wrapped is mock_keydb.return_value


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
    """backend=memcached + aiomcache available → MemcachedBackend() (wrapped)."""
    # Inject fake aiomcache into sys.modules (factory does `import aiomcache`)
    fake_aiomcache = MagicMock(name="aiomcache_module")
    with (
        patch.dict(sys.modules, {"aiomcache": fake_aiomcache}),
        patch.object(factory, "MemcachedBackend") as mock_memcached,
    ):
        result = create_cache_backend(cfg_memcached)
        # Import succeeded, MemcachedBackend instantiated
        mock_memcached.assert_called_once_with()
        # B-03: возвращённый backend обёрнут в TenantCacheBackend.
        assert isinstance(result, TenantCacheBackend)
        assert result.wrapped is mock_memcached.return_value


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
        "src.backend.infrastructure.clients.storage.redis.get_redis_client", return_value=fake_singleton
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
        "src.backend.infrastructure.clients.storage.redis.get_redis_client", return_value=fake_singleton
    ):
        result = factory._redis_client()
    assert result is fake_raw


def test_redis_client_raises_if_not_initialized() -> None:
    """_redis_client raises RuntimeError if neither _raw_client nor client set."""
    fake_singleton = MagicMock(spec=[])  # no attributes
    with patch(
        "src.backend.infrastructure.clients.storage.redis.get_redis_client", return_value=fake_singleton
    ):
        with pytest.raises(RuntimeError, match="redis_client не инициализирован"):
            factory._redis_client()


# ── default settings (no arg) ──────────────────────────────────────


def test_no_settings_uses_singleton() -> None:
    """create_cache_backend() with no arg uses cache_settings singleton (wrapped)."""
    with patch.object(factory, "MemoryBackend") as mock_mem:
        # default cache_settings has backend=redis, override via cache_settings
        with patch.object(factory, "cache_settings", backend="memory"):
            result = create_cache_backend()
        mock_mem.assert_called_once()
        # B-03: возвращённый backend обёрнут в TenantCacheBackend.
        assert isinstance(result, TenantCacheBackend)
        assert result.wrapped is mock_mem.return_value


# ── logger name (smoke) ─────────────────────────────────────────────


def test_module_logger() -> None:
    """Module has a logger named 'infrastructure.cache.factory'."""
    assert factory.logger.name == "infrastructure.cache.factory"


# ── B-03: TenantCacheBackend wrapping (cycle 34) ──────────────────


def test_create_cache_backend_wraps_in_tenant_cache_backend(
    cfg_memory: CacheSettings,
) -> None:
    """B-03: create_cache_backend оборачивает результат в TenantCacheBackend.

    Регрессионный тест для архитектурного долга: TenantCacheBackend
    существовал (Sprint 21 K1 W2), но не был подключён в factory.py —
    все cache backends создавались без tenant prefix, открывая
    cache poisoning (B-03). Теперь обёртка гарантирует, что все
    cache consumers получают tenant-scoped keys.
    """
    with patch.object(factory, "MemoryBackend") as mock_mem:
        result = create_cache_backend(cfg_memory)

    assert isinstance(result, TenantCacheBackend), (
        "create_cache_backend должен возвращать TenantCacheBackend wrapper, "
        f"не {type(result).__name__}"
    )
    assert result.wrapped is mock_mem.return_value


def test_create_cache_backend_wraps_for_all_4_backends() -> None:
    """B-03: wrapper применяется к memory/redis/keydb — memcached skip (требует aiomcache).

    Cycle 34 (ретроспектива): в multi-tenant production все 4 backend
    типа должны быть tenant-scoped. Тест проверяет wrapping для
    memory/redis/keydb (memcached требует реального aiomcache dep).
    """
    from src.backend.infrastructure.cache.backends.keydb import KeyDBBackend
    from src.backend.infrastructure.cache.backends.memory import MemoryBackend
    from src.backend.infrastructure.cache.backends.redis import RedisBackend

    cfgs = [
        (CacheSettings(backend="memory"), MemoryBackend),
        (CacheSettings(backend="redis"), RedisBackend),
        (CacheSettings(backend="keydb"), KeyDBBackend),
    ]
    for cfg, expected_inner_type in cfgs:
        result = create_cache_backend(cfg)
        assert isinstance(result, TenantCacheBackend), (
            f"backend={cfg.backend}: expected TenantCacheBackend, got {type(result).__name__}"
        )
        assert isinstance(result.wrapped, expected_inner_type), (
            f"backend={cfg.backend}: wrapped is {type(result.wrapped).__name__}, "
            f"expected {expected_inner_type.__name__}"
        )


def test_wrapped_backend_uses_unscoped_prefix_when_flag_off_and_no_tenant(
    cfg_memory: CacheSettings,
) -> None:
    """B-03: при flag=OFF (autouse fixture) wrapper не применяет prefix.

    Cycle 34 contract: TenantCacheBackend при выключенном feature flag
    ведёт себя как no-op (прямая делегация, без prefix). Это позволяет
    постепенно включать tenant cache prefix через feature flag без
    breaking changes.
    """
    from src.backend.core.config.features import feature_flags

    assert feature_flags.tenant_cache_prefix_enabled is False  # autouse

    with patch.object(factory, "MemoryBackend"):
        wrapper = create_cache_backend(cfg_memory)
        # Wrapper создан, но при flag=OFF prefix=``.
        assert wrapper._prefix() == ""


def test_wrapped_backend_uses_tenant_prefix_when_flag_on_and_tenant_set(
    monkeypatch: pytest.MonkeyPatch, cfg_memory: CacheSettings
) -> None:
    """B-03: при flag=ON + tenant в ContextVar → префикс ``tenant:{id}:``."""
    from src.backend.core.config.features import feature_flags
    from src.backend.core.tenancy import TenantContext, _current

    # Override autouse fixture для этого теста.
    monkeypatch.setattr(feature_flags, "tenant_cache_prefix_enabled", True)

    fake_tenant = TenantContext(tenant_id="bank_a")
    token = _current.set(fake_tenant)
    try:
        with patch.object(factory, "MemoryBackend"):
            wrapper = create_cache_backend(cfg_memory)
            # С tenant в context → префикс tenant:bank_a:.
            assert wrapper._prefix() == "tenant:bank_a:"
    finally:
        _current.reset(token)


def test_wrapped_backend_uses_unscoped_prefix_when_flag_on_but_no_tenant(
    monkeypatch: pytest.MonkeyPatch, cfg_memory: CacheSettings
) -> None:
    """B-03: при flag=ON без tenant → ``tenant:_unscoped_:`` (изоляция).

    Cycle 34: даже при включённом tenant cache prefix, ключи без
    tenant контекста изолируются в dedicated namespace, чтобы НЕ
    смешиваться с tenant-scoped ключами.
    """
    from src.backend.core.config.features import feature_flags
    from src.backend.core.tenancy import _current

    monkeypatch.setattr(feature_flags, "tenant_cache_prefix_enabled", True)

    # Reset tenant context на всякий случай (если leaked from earlier).
    try:
        token = _current.set(None)
    except LookupError:
        token = None
    try:
        with patch.object(factory, "MemoryBackend"):
            wrapper = create_cache_backend(cfg_memory)
            assert wrapper._prefix() == "tenant:_unscoped_:"
    finally:
        if token is not None:
            _current.reset(token)
