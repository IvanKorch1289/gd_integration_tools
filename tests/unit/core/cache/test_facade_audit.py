"""Smoke tests for cache facade (cycle 163 → cycle 167).

Cycle 163 cache audit found two ``UnifiedCacheFacade`` classes. After
ADR-0352 Stages 1-4 (cycles 163-167), canonical ABC остаётся в core,
production impl — в services (extends ABC).

Cycle 167 (Stage 4): core-facade concrete impls (MemoryCacheFacade,
FallbackCacheFacade, RedisCacheFacade) REMOVED. ABC + CacheError +
CacheInvalidationPolicy — единственное что осталось.

Tests verify:
1. ABC остаётся canonical в core.
2. Services facade extends ABC (Stage 2 merge).
3. Concrete impls REMOVED (Stage 4).
4. DiskCacheBackend (infrastructure) — canonical disk-tier.

See docs/adr/0352-cache-facade-duplication.md.
"""

from __future__ import annotations

import pytest


class TestCoreUnifiedCacheFacadeExists:
    """Document the core ABC (canonical after Stage 4)."""

    def test_import_works(self) -> None:
        """``UnifiedCacheFacade`` ABC is importable."""
        from src.backend.core.cache.facade import (
            UnifiedCacheFacade as CoreUnifiedCacheFacade,
        )

        assert CoreUnifiedCacheFacade is not None

    def test_reexport_from_core_cache(self) -> None:
        """``UnifiedCacheFacade`` re-exported from ``src.backend.core.cache``."""
        from src.backend.core.cache import UnifiedCacheFacade

        from src.backend.core.cache.facade import (
            UnifiedCacheFacade as CoreDirect,
        )

        assert UnifiedCacheFacade is CoreDirect

    def test_abc_methods(self) -> None:
        """ABC имеет abstract methods: get/set/delete/delete_by_tag/exists/healthcheck."""
        from src.backend.core.cache.facade import UnifiedCacheFacade

        abstract_methods = set(UnifiedCacheFacade.__abstractmethods__)
        expected = {"get", "set", "delete", "delete_by_tag", "exists", "healthcheck"}
        assert expected.issubset(abstract_methods), (
            f"Missing abstract methods: {expected - abstract_methods}"
        )

    def test_cache_error_and_policy_exported(self) -> None:
        """``CacheError`` + ``CacheInvalidationPolicy`` экспортированы."""
        from src.backend.core.cache import CacheError, CacheInvalidationPolicy

        assert CacheError is not None
        assert CacheInvalidationPolicy is not None

    def test_concrete_impls_removed(self) -> None:
        """Cycle 167 (Stage 4): MemoryCacheFacade, FallbackCacheFacade,
        RedisCacheFacade REMOVED из core.cache.facade.
        """
        # Direct submodule imports should fail.
        for name in ("MemoryCacheFacade", "FallbackCacheFacade", "RedisCacheFacade"):
            with pytest.raises(ImportError):
                __import__(
                    "src.backend.core.cache.facade",
                    fromlist=[name],
                )
                from src.backend.core.cache.facade import name  # noqa: F401

    def test_concrete_impls_removed_via_core_cache(self) -> None:
        """Concrete impls также удалены из ``src.backend.core.cache.__all__``."""
        from src.backend.core.cache import __all__

        for name in (
            "MemoryCacheFacade",
            "FallbackCacheFacade",
            "RedisCacheFacade",
            "DiskCacheFacade",
        ):
            assert name not in __all__, (
                f"{name} should NOT be in core.cache.__all__ (Stage 4 REMOVE)"
            )

    def test_disk_cache_facade_removed(self) -> None:
        """Cycle 164: DiskCacheFacade (core) удалена."""
        with pytest.raises(ImportError):
            from src.backend.core.cache.facade import DiskCacheFacade  # noqa: F401

    def test_disk_cache_backend_canonical(self) -> None:
        """Canonical disk-tier — DiskCacheBackend (infrastructure)."""
        from src.backend.infrastructure.cache.backends.disk import DiskCacheBackend

        assert DiskCacheBackend is not None
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            backend = DiskCacheBackend(base_path=Path(tmp))
            assert backend is not None


class TestServicesUnifiedCacheFacadeExists:
    """Document the services-level concrete facade (extends core ABC)."""

    def test_import_works(self) -> None:
        """``UnifiedCacheFacade`` is importable from ``services.cache.facade``."""
        from src.backend.services.cache.facade import (
            UnifiedCacheFacade as ServicesUnifiedCacheFacade,
        )

        assert ServicesUnifiedCacheFacade is not None

    def test_reexport_from_services_cache(self) -> None:
        """``UnifiedCacheFacade`` re-exported from ``src.backend.services.cache``."""
        from src.backend.services.cache import UnifiedCacheFacade

        from src.backend.services.cache.facade import (
            UnifiedCacheFacade as ServicesDirect,
        )

        assert UnifiedCacheFacade is ServicesDirect

    def test_cache_result_dataclass_exists(self) -> None:
        """``CacheResult`` (value/hit/backend) is exposed."""
        from src.backend.services.cache.facade import CacheResult

        result = CacheResult(value=b"x", hit=True, backend="primary")
        assert result.value == b"x"
        assert result.hit is True
        assert result.backend == "primary"

    def test_get_unified_cache_facade_helper_exists(self) -> None:
        """``get_unified_cache_facade`` is exposed at package level."""
        from src.backend.services.cache import get_unified_cache_facade

        assert get_unified_cache_facade is not None


class TestFacadesAreDifferent:
    """Document the API differences post-Stage-2 merge."""

    def test_different_classes(self) -> None:
        """Core ABC vs services concrete — разные классы."""
        from src.backend.core.cache import UnifiedCacheFacade as Core
        from src.backend.services.cache import UnifiedCacheFacade as Services

        assert Core is not Services

    def test_services_abc_returns_bytes(self) -> None:
        """Services.get() (ABC-style) returns bytes | None."""
        import inspect

        from src.backend.services.cache import UnifiedCacheFacade as Services

        sig = inspect.signature(Services.get)
        assert "bytes" in str(sig.return_annotation)

    def test_services_get_ns_returns_cache_result(self) -> None:
        """Services.get_ns() returns CacheResult (dataclass)."""
        import inspect

        from src.backend.services.cache import UnifiedCacheFacade as Services

        sig = inspect.signature(Services.get_ns)
        assert "CacheResult" in str(sig.return_annotation)

    def test_core_returns_bytes(self) -> None:
        """Core.get() returns bytes | None."""
        import inspect

        from src.backend.core.cache import UnifiedCacheFacade as Core

        sig = inspect.signature(Core.get)
        assert "bytes" in str(sig.return_annotation)

    def test_services_is_core_subclass(self) -> None:
        """Cycle 165 (Stage 2): services.UnifiedCacheFacade IS-A core ABC."""
        from src.backend.core.cache import UnifiedCacheFacade as Core
        from src.backend.services.cache import UnifiedCacheFacade as Services

        assert issubclass(Services, Core)


class TestCanonicalEntryPoints:
    """Public API re-exports per CLAUDE.md R1."""

    def test_core_cache_all_exports_unified(self) -> None:
        """``src.backend.core.cache.__all__`` contains ``UnifiedCacheFacade``."""
        from src.backend.core.cache import __all__

        assert "UnifiedCacheFacade" in __all__

    def test_services_cache_all_exports_unified(self) -> None:
        """``src.backend.services.cache.__all__`` contains ``UnifiedCacheFacade``."""
        from src.backend.services.cache import __all__

        assert "UnifiedCacheFacade" in __all__