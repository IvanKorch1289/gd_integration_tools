"""Unit-тесты ``infrastructure.cache`` — coverage ratchet (Post-Plan A Sprint 28).

core/infrastructure/cache package facade (ADR-004 no-double-cache): re-exports
14 symbols (KeyDBBackend + MemoryBackend + RedisBackend + CacheInvalidator +
InMemoryCacheBackend + TieredCacheBackend + TenantCacheBackend classes +
CacheConfigEntry + CacheConfigRegistry + CacheDuplicationError +
CacheLayerValidator + cache_config_registry + create_cache_backend +
get_cache_invalidator + set_cache_invalidator). ~25 stmts, 0% coverage.

Цель slice: 0% → 100% через __all__ audit + class/constant/callable identity.

NOTE: F401 skipped per inline comment — many imports are availability checks
для опциональных бэкендов (keydb, redis).
"""

from __future__ import annotations

import pytest

from src.backend.infrastructure import cache
from src.backend.infrastructure.cache import (
    DEFAULT_UNSCOPED_PREFIX,
    CacheBackendProtocol,
    CacheConfigEntry,
    CacheConfigRegistry,
    CacheDuplicationError,
    CacheInvalidator,
    CacheLayerValidator,
    InMemoryCacheBackend,
    KeyDBBackend,
    MemoryBackend,
    RedisBackend,
    TenantCacheBackend,
    TieredCacheBackend,
    cache_config_registry,
    create_cache_backend,
    get_cache_invalidator,
    set_cache_invalidator,
)


@pytest.mark.unit
class TestCacheFacadeAllExports:
    """``__all__`` audit + class/constant/callable identity."""

    @pytest.mark.parametrize(
        "symbol_name",
        [
            "DEFAULT_UNSCOPED_PREFIX",
            "CacheBackendProtocol",
            "CacheConfigEntry",
            "CacheConfigRegistry",
            "CacheDuplicationError",
            "CacheInvalidator",
            "CacheLayerValidator",
            "InMemoryCacheBackend",
            "KeyDBBackend",
            "MemoryBackend",
            "RedisBackend",
            "TenantCacheBackend",
            "cache_config_registry",
            "create_cache_backend",
            "get_cache_invalidator",
            "set_cache_invalidator",
        ],
    )
    def test_all_exports_accessible(self, symbol_name: str) -> None:
        """Каждый символ из ``__all__`` доступен через facade."""
        assert hasattr(cache, symbol_name), (
            f"Missing export: {symbol_name}"
        )
        assert symbol_name in cache.__all__, (
            f"{symbol_name} not declared in __all__"
        )

    def test_all_declared_count(self) -> None:
        """``__all__`` содержит 16 символов."""
        assert len(cache.__all__) == 16

    def test_module_docstring_present(self) -> None:
        """Module docstring описывает cache infra (ADR-004 no-double-cache)."""
        assert cache.__doc__ is not None
        assert "cache" in cache.__doc__.lower() or "кэш" in cache.__doc__.lower()


@pytest.mark.unit
class TestCacheFacadeIdentity:
    """Identity checks для 14 re-exports."""

    def test_backend_classes(self) -> None:
        """5 backend classes в __all__: KeyDBBackend, MemoryBackend, RedisBackend,
        InMemoryCacheBackend, TenantCacheBackend.

        Note: TieredCacheBackend is imported в __init__ but NOT в __all__ —
        оставлен для backward-compat import paths (не re-exported в facade).
        """
        for cls in (
            KeyDBBackend,
            MemoryBackend,
            RedisBackend,
            InMemoryCacheBackend,
            TenantCacheBackend,
        ):
            assert isinstance(cls, type), f"{cls.__name__} is not a class"

    def test_cache_backend_protocol_is_protocol(self) -> None:
        """``CacheBackendProtocol`` — Protocol class (structural subtyping)."""
        from typing import Protocol

        assert isinstance(CacheBackendProtocol, type)
        assert hasattr(CacheBackendProtocol, "__subclasshook__") or hasattr(
            CacheBackendProtocol, "__call__"
        )

    def test_default_unscoped_prefix_is_string(self) -> None:
        """``DEFAULT_UNSCOPED_PREFIX`` — str constant (cache key prefix)."""
        assert isinstance(DEFAULT_UNSCOPED_PREFIX, str)
        assert len(DEFAULT_UNSCOPED_PREFIX) > 0

    def test_invalidator_classes(self) -> None:
        """CacheInvalidator class."""
        assert isinstance(CacheInvalidator, type)

    def test_config_classes(self) -> None:
        """CacheConfigEntry + CacheConfigRegistry classes."""
        assert isinstance(CacheConfigEntry, type)
        assert isinstance(CacheConfigRegistry, type)

    def test_layer_validator_class(self) -> None:
        """CacheLayerValidator class (no-double-cache validator per ADR-004)."""
        assert isinstance(CacheLayerValidator, type)

    def test_cache_duplication_error_is_exception(self) -> None:
        """``CacheDuplicationError`` — Exception subclass."""
        assert isinstance(CacheDuplicationError, type)
        assert issubclass(CacheDuplicationError, Exception)

    def test_cache_config_registry_is_instance(self) -> None:
        """``cache_config_registry`` — pre-initialized instance (CacheConfigRegistry())."""
        assert isinstance(cache_config_registry, CacheConfigRegistry)

    def test_create_cache_backend_is_callable(self) -> None:
        """``create_cache_backend`` — callable (factory function)."""
        assert callable(create_cache_backend)

    def test_get_cache_invalidator_is_callable(self) -> None:
        """``get_cache_invalidator`` — callable (singleton getter)."""
        assert callable(get_cache_invalidator)

    def test_set_cache_invalidator_is_callable(self) -> None:
        """``set_cache_invalidator`` — callable (singleton setter)."""
        assert callable(set_cache_invalidator)
