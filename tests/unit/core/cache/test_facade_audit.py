"""Smoke tests for cache facade audit findings (cycle 163).

Cycle 163 cache audit found two ``UnifiedCacheFacade`` classes:

1. ``src.backend.core.cache.facade.UnifiedCacheFacade`` — ABC, no namespace.
2. ``src.backend.services.cache.facade.UnifiedCacheFacade`` — concrete,
   namespace-aware, capability-checked, DI-registered.

These tests:

1. Document both classes' existence (regression — prevents one from being
   silently removed before ADR-0352 stages 2-4).
2. Verify the public re-exports work.
3. Smoke-test that both facades can be instantiated with minimal args.

These are NOT unification tests — they encode the current (problematic)
state so that:

- ADR-0352 stage 2 (merge) can update tests in one place.
- Stage 4 (REMOVE) can verify removal.

See docs/adr/0352-cache-facade-duplication.md for the merge plan.
"""

from __future__ import annotations


class TestCoreUnifiedCacheFacadeExists:
    """Document the core ABC."""

    def test_import_works(self) -> None:
        """``UnifiedCacheFacade`` is importable from ``core.cache.facade``."""
        from src.backend.core.cache.facade import (
            UnifiedCacheFacade as CoreUnifiedCacheFacade,
        )

        assert CoreUnifiedCacheFacade is not None

    def test_reexport_from_core_cache(self) -> None:
        """``UnifiedCacheFacade`` is re-exported from ``src.backend.core.cache``."""
        from src.backend.core.cache import UnifiedCacheFacade

        # Should be the same class as core.cache.facade.
        from src.backend.core.cache.facade import (
            UnifiedCacheFacade as CoreDirect,
        )

        assert UnifiedCacheFacade is CoreDirect

    def test_concrete_subclasses_exist(self) -> None:
        """Core facade has MemoryCacheFacade, FallbackCacheFacade
        (re-exported). RedisCacheFacade / DiskCacheFacade exist in the
        module but are NOT in __all__ — they are imported via direct
        submodule access (``src.backend.core.cache.facade``)."""
        from src.backend.core.cache import (
            FallbackCacheFacade,
            MemoryCacheFacade,
        )

        # These ARE in __all__ — public.
        for cls in (MemoryCacheFacade, FallbackCacheFacade):
            assert cls is not None

        # These are NOT in __all__ — accessible only via .facade submodule.
        from src.backend.core.cache.facade import (
            DiskCacheFacade,
            RedisCacheFacade,
        )

        for cls in (RedisCacheFacade, DiskCacheFacade):
            assert cls is not None

    def test_memory_facade_basic(self) -> None:
        """MemoryCacheFacade get/set round-trip works."""
        import asyncio

        from src.backend.core.cache import MemoryCacheFacade

        async def _check() -> None:
            cache = MemoryCacheFacade(maxsize=16, default_ttl=60)
            await cache.set("k", b"v")
            assert await cache.get("k") == b"v"
            assert await cache.exists("k") is True

        asyncio.run(_check())


class TestServicesUnifiedCacheFacadeExists:
    """Document the services-level concrete facade."""

    def test_import_works(self) -> None:
        """``UnifiedCacheFacade`` is importable from ``services.cache.facade``."""
        from src.backend.services.cache.facade import (
            UnifiedCacheFacade as ServicesUnifiedCacheFacade,
        )

        assert ServicesUnifiedCacheFacade is not None

    def test_reexport_from_services_cache(self) -> None:
        """``UnifiedCacheFacade`` is re-exported from ``src.backend.services.cache``."""
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
    """Document the API drift between the two facades.

    When ADR-0352 is implemented, these tests will be updated.
    """

    def test_different_classes(self) -> None:
        """The two ``UnifiedCacheFacade`` are NOT the same class."""
        from src.backend.core.cache import UnifiedCacheFacade as Core
        from src.backend.services.cache import UnifiedCacheFacade as Services

        # They are NOT the same — that is the problem we are documenting.
        assert Core is not Services

    def test_services_has_namespace(self) -> None:
        """Services facade has namespace-aware methods."""
        import inspect

        from src.backend.services.cache import UnifiedCacheFacade as Services

        # get() should accept a namespace kwarg.
        sig = inspect.signature(Services.get)
        assert "namespace" in sig.parameters

    def test_core_lacks_namespace(self) -> None:
        """Core facade does NOT have namespace kwarg (ABC)."""
        import inspect

        from src.backend.core.cache import UnifiedCacheFacade as Core

        sig = inspect.signature(Core.get)
        assert "namespace" not in sig.parameters

    def test_services_returns_cache_result(self) -> None:
        """Services.get() returns CacheResult (dataclass)."""
        import inspect

        from src.backend.services.cache import UnifiedCacheFacade as Services

        # Return annotation should be CacheResult (not bytes).
        sig = inspect.signature(Services.get)
        assert "CacheResult" in str(sig.return_annotation)

    def test_core_returns_bytes(self) -> None:
        """Core.get() returns bytes | None."""
        import inspect

        from src.backend.core.cache import UnifiedCacheFacade as Core

        sig = inspect.signature(Core.get)
        # Return annotation should mention bytes.
        assert "bytes" in str(sig.return_annotation)


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