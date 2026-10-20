"""Tests for 3 memory cache classes — distinct roles (cycle 164, ADR-0352 Stage 6).

CACHE_AUDIT_2026-10-20 §6 mentions "MemoryCacheFacade vs LruMemoryCache" as a
known inconsistency. Cycle 164 analysis: this is INTENTIONAL design — three
memory classes serve different layers with different responsibilities:

1. ``MemoryCacheFacade`` (core/cache/facade.py) — ``UnifiedCacheFacade`` ABC
   impl. Used by ``core/di/providers/cache.py::get_cache_facade`` for
   dev_light/test fallback + ``FallbackCacheFacade`` chain.

2. ``MemoryBackend`` (infrastructure/cache/backends/memory.py) —
   ``CacheBackend`` interface impl. Used by services.UnifiedCacheFacade 3-tier
   (primary/memory/disk).

3. ``LruMemoryCache`` (infrastructure/cache/lru_cache.py) — duck-typed
   L1 of RAG 3-tier router. Has prometheus metrics + Any types (RAG embeddings).

These tests verify each class works in its distinct role. If anyone tries
to "consolidate" — they must explicitly motivate the trade-off (loss of
tag invalidation / delete_pattern / metrics).
"""

from __future__ import annotations

import asyncio


class TestMemoryCacheFacadeCoreRole:
    """``MemoryCacheFacade`` (core) — UnifiedCacheFacade ABC impl with tags."""

    async def test_basic_get_set(self) -> None:
        """Round-trip get/set works."""
        from src.backend.core.cache.facade import MemoryCacheFacade

        cache = MemoryCacheFacade(maxsize=10, default_ttl=60)
        await cache.set("k", b"value")
        assert await cache.get("k") == b"value"

    async def test_tag_invalidation_unique_to_memory_cache_facade(self) -> None:
        """Tag invalidation — UNIQUE feature of MemoryCacheFacade.

        MemoryBackend and LruMemoryCache do NOT support delete_by_tag.
        This test verifies MemoryCacheFacade preserves this capability.
        """
        from src.backend.core.cache.facade import MemoryCacheFacade

        cache = MemoryCacheFacade(maxsize=10, default_ttl=60)
        await cache.set("a", b"1", tags=["group1"])
        await cache.set("b", b"2", tags=["group1", "group2"])
        await cache.set("c", b"3", tags=["group2"])

        deleted = await cache.delete_by_tag("group1")
        assert deleted == 2  # a, b
        assert await cache.get("a") is None
        assert await cache.get("b") is None
        assert await cache.get("c") == b"3"  # only group2, preserved

    async def test_healthcheck_always_true(self) -> None:
        """In-memory cache is always healthy."""
        from src.backend.core.cache.facade import MemoryCacheFacade

        cache = MemoryCacheFacade()
        assert await cache.healthcheck() is True

    async def test_uses_unified_cache_facade_abc(self) -> None:
        """MemoryCacheFacade IS-A UnifiedCacheFacade (ABC inheritance)."""
        from src.backend.core.cache.facade import (
            MemoryCacheFacade,
            UnifiedCacheFacade,
        )

        assert issubclass(MemoryCacheFacade, UnifiedCacheFacade)


class TestMemoryBackendInfrastructureRole:
    """``MemoryBackend`` (infrastructure) — CacheBackend interface impl."""

    async def test_basic_get_set(self) -> None:
        """Round-trip get/set works."""
        from src.backend.infrastructure.cache.backends.memory import MemoryBackend

        backend = MemoryBackend(maxsize=10, default_ttl=60)
        await backend.set("k", b"value")
        assert await backend.get("k") == b"value"

    async def test_delete_pattern_unique_to_memory_backend(self) -> None:
        """delete_pattern — UNIQUE feature of MemoryBackend.

        MemoryCacheFacade and LruMemoryCache do NOT support pattern deletion.
        """
        from src.backend.infrastructure.cache.backends.memory import MemoryBackend

        backend = MemoryBackend(maxsize=10, default_ttl=60)
        await backend.set("user:1", b"data1")
        await backend.set("user:2", b"data2")
        await backend.set("order:1", b"data3")

        await backend.delete_pattern("user:*")
        assert await backend.get("user:1") is None
        assert await backend.get("user:2") is None
        assert await backend.get("order:1") == b"data3"

    async def test_no_tag_invalidation(self) -> None:
        """MemoryBackend does NOT support tag invalidation (unlike MemoryCacheFacade)."""
        from src.backend.infrastructure.cache.backends.memory import MemoryBackend

        backend = MemoryBackend()
        # delete_by_tag should not exist on MemoryBackend.
        assert not hasattr(backend, "delete_by_tag") or not callable(
            getattr(backend, "delete_by_tag", None)
        ), (
            "MemoryBackend should NOT have delete_by_tag — this is a "
            "MemoryCacheFacade-only feature (distinct role)."
        )

    async def test_no_healthcheck(self) -> None:
        """MemoryBackend does NOT have healthcheck (unlike MemoryCacheFacade)."""
        from src.backend.infrastructure.cache.backends.memory import MemoryBackend

        backend = MemoryBackend()
        # CacheBackend interface (which MemoryBackend implements) does not
        # require healthcheck. Different from UnifiedCacheFacade.
        # We just verify MemoryBackend doesn't accidentally add it.
        assert not hasattr(backend, "healthcheck") or not callable(
            getattr(backend, "healthcheck", None)
        )

    async def test_uses_cache_backend_interface(self) -> None:
        """MemoryBackend IS-A CacheBackend (interface inheritance)."""
        from src.backend.core.interfaces.cache import CacheBackend
        from src.backend.infrastructure.cache.backends.memory import MemoryBackend

        assert issubclass(MemoryBackend, CacheBackend)


class TestLruMemoryCacheRouterRole:
    """``LruMemoryCache`` (infrastructure) — RAG 3-tier router L1."""

    async def test_basic_get_set(self) -> None:
        """Round-trip get/set works (Any types, not just bytes)."""
        from src.backend.infrastructure.cache.lru_cache import LruMemoryCache

        cache = LruMemoryCache(max_size=10, ttl_seconds=60, scope="test")
        # Any types — embedding-like objects.
        await cache.set("k1", {"vector": [0.1, 0.2, 0.3], "id": "doc-1"})
        await cache.set("k2", [1, 2, 3])
        await cache.set("k3", "string-value")

        assert await cache.get("k1") == {
            "vector": [0.1, 0.2, 0.3],
            "id": "doc-1",
        }
        assert await cache.get("k2") == [1, 2, 3]
        assert await cache.get("k3") == "string-value"

    async def test_prometheus_metrics_scope_unique(self) -> None:
        """LruMemoryCache has unique scope label for Prometheus metrics."""
        from src.backend.infrastructure.cache.lru_cache import LruMemoryCache

        cache_a = LruMemoryCache(scope="rag-l1-embeddings")
        cache_b = LruMemoryCache(scope="rag-l1-messages")

        assert cache_a.scope == "rag-l1-embeddings"
        assert cache_b.scope == "rag-l1-messages"
        # Different scopes allow separate metric tracking per cache instance.
        assert cache_a.scope != cache_b.scope

    async def test_no_tag_or_pattern_delete(self) -> None:
        """LruMemoryCache does NOT support tag or pattern deletion.

        L1 tier of RAG router uses invalidation() to clear whole cache.
        No per-tag or per-pattern operations (different role).
        """
        from src.backend.infrastructure.cache.lru_cache import LruMemoryCache

        cache = LruMemoryCache()
        # LruMemoryCache has invalidate() and clear() but NOT delete_by_tag
        # or delete_pattern. These are role-specific to other classes.
        assert not hasattr(cache, "delete_by_tag") or not callable(
            getattr(cache, "delete_by_tag", None)
        )
        assert not hasattr(cache, "delete_pattern") or not callable(
            getattr(cache, "delete_pattern", None)
        )

    async def test_used_by_tier_router(self) -> None:
        """LruMemoryCache is the L1 of infrastructure.ai.semantic_cache.TierRouter."""
        # This test verifies the actual integration: that TierRouter uses
        # LruMemoryCache as L1 (not MemoryBackend or MemoryCacheFacade).
        from src.backend.infrastructure.ai.semantic_cache import TierRouter

        # Stub L2 and L3 backends.
        class _StubBackend:
            async def get(self, key):
                return None

            async def set(self, key, value, ttl=None):
                pass

        router = TierRouter(l1=None, l2=_StubBackend(), l3=_StubBackend())
        # After init, l1 should default to LruMemoryCache.
        assert router.l1 is not None
        # The default L1 is LruMemoryCache (NOT MemoryBackend or MemoryCacheFacade).
        from src.backend.infrastructure.cache.lru_cache import LruMemoryCache

        assert isinstance(router.l1, LruMemoryCache)


class TestThreeClassesHaveDifferentRoles:
    """Verify the three classes have DIFFERENT interfaces (no accidental duplicates)."""

    def test_different_base_classes(self) -> None:
        """Each class implements a DIFFERENT interface (or none)."""
        from src.backend.core.cache.facade import MemoryCacheFacade
        from src.backend.core.interfaces.cache import CacheBackend
        from src.backend.infrastructure.cache.backends.memory import MemoryBackend
        from src.backend.infrastructure.cache.lru_cache import LruMemoryCache

        # MemoryCacheFacade → UnifiedCacheFacade ABC (NOT CacheBackend).
        from src.backend.core.cache.facade import UnifiedCacheFacade

        assert issubclass(MemoryCacheFacade, UnifiedCacheFacade)
        assert not issubclass(MemoryCacheFacade, CacheBackend)

        # MemoryBackend → CacheBackend interface.
        assert issubclass(MemoryBackend, CacheBackend)

        # LruMemoryCache — duck-typed (no interface inheritance).
        # (Per its docstring: "Совместим с CacheBackend, но не наследует от него".)
        assert not issubclass(LruMemoryCache, CacheBackend)
        assert not issubclass(LruMemoryCache, UnifiedCacheFacade)

    def test_different_type_signatures(self) -> None:
        """Each class has DIFFERENT return type semantics."""
        from src.backend.core.cache.facade import MemoryCacheFacade
        from src.backend.infrastructure.cache.backends.memory import MemoryBackend
        from src.backend.infrastructure.cache.lru_cache import LruMemoryCache

        # MemoryCacheFacade.get → bytes | None (tag-aware policy).
        facade = MemoryCacheFacade()
        assert "bytes" in str(facade.get.__annotations__.get("return", ""))

        # MemoryBackend.get → bytes | None (no policy).
        backend = MemoryBackend()
        assert "bytes" in str(backend.get.__annotations__.get("return", ""))

        # LruMemoryCache.get → Any | None (RAG embeddings, etc).
        lru = LruMemoryCache()
        assert "Any" in str(lru.get.__annotations__.get("return", ""))


class TestNoUnintendedConsolidation:
    """Guards against accidental consolidation."""

    def test_three_classes_are_distinct_objects(self) -> None:
        """Sanity: three distinct classes, no aliases."""
        from src.backend.core.cache.facade import MemoryCacheFacade
        from src.backend.infrastructure.cache.backends.memory import MemoryBackend
        from src.backend.infrastructure.cache.lru_cache import LruMemoryCache

        assert MemoryCacheFacade is not MemoryBackend
        assert MemoryCacheFacade is not LruMemoryCache
        assert MemoryBackend is not LruMemoryCache

    def test_import_paths_distinct(self) -> None:
        """Each class lives in a distinct module path."""
        from src.backend.core.cache.facade import MemoryCacheFacade as MCF
        from src.backend.infrastructure.cache.backends.memory import (
            MemoryBackend as MB,
        )
        from src.backend.infrastructure.cache.lru_cache import LruMemoryCache as LMC

        assert MCF.__module__ == "src.backend.core.cache.facade"
        assert MB.__module__ == "src.backend.infrastructure.cache.backends.memory"
        assert LMC.__module__ == "src.backend.infrastructure.cache.lru_cache"