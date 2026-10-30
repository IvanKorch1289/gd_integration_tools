"""Tests for 3 memory cache classes — distinct roles (cycle 164, ADR-0352 Stage 6).

CACHE_AUDIT_2026-10-20 §6 mentions "MemoryCacheFacade vs LruMemoryCache" as a
known inconsistency. Cycle 164 analysis: this is INTENTIONAL design — three
memory classes serve different layers with different responsibilities:

1. ``MemoryCacheFacade`` (core/cache/facade.py) — ``UnifiedCacheFacade`` ABC
   impl. USED BY ``core/di/providers/cache.py::get_cache_facade`` for
   dev_light/test fallback + ``FallbackCacheFacade`` chain.

   **Cycle 167 (ADR-0352 Stage 4)**: REMOVED из ``core.cache.facade``.
   Тесты для MemoryCacheFacade удалены (см. ADR-0352.1 migration guide).
   Disk-tier покрывается DiskCacheBackend (infrastructure):
   см. tests/unit/infrastructure/cache/test_disk_backend.py +
   test_disk_focused.py.

2. ``MemoryBackend`` (infrastructure/cache/backends/memory.py) —
   ``CacheBackend`` interface impl. Used by services.UnifiedCacheFacade 3-tier
   (primary/memory/disk).

3. ``LruMemoryCache`` (infrastructure/cache/lru_cache.py) — duck-typed
   L1 of RAG 3-tier router. Has prometheus metrics + Any types (RAG embeddings).

After Stage 4 (cycle 167):
- core.cache.MemoryCacheFacade REMOVED (только ABC + CacheError + Policy).
- services.cache.UnifiedCacheFacade — canonical production facade.
- MemoryBackend + LruMemoryCache — separate abstractions для разных слоёв.
"""

from __future__ import annotations

import asyncio


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

        MemoryCacheFacade и LruMemoryCache do NOT support pattern deletion.
        MemoryCacheFacade удалена в Stage 4.
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

    async def test_supports_tag_invalidation(self) -> None:
        """MemoryBackend поддерживает tag-инвалидацию (ADR-0401).

        Cycle 167: MemoryCacheFacade удалена, tag-инвалидация осталась
        только в services.UnifiedCacheFacade. ADR-0401: глобальный
        ``CacheInvalidator`` чистит только primary-тир, поэтому
        fallback-уровни (L1 memory / L3 disk) должны уметь
        ``delete_by_tag`` — иначе после отказа Redis клиент получал
        stale-значения из fallback'а.
        """
        from src.backend.infrastructure.cache.backends.memory import MemoryBackend

        backend = MemoryBackend()
        assert callable(getattr(backend, "delete_by_tag", None))
        await backend.set("k1", b"v1")
        await backend.bind_key_to_tag("entity:orders", "k1")
        assert await backend.delete_by_tag("entity:orders") == 1
        assert await backend.get("k1") is None

    async def test_no_healthcheck(self) -> None:
        """MemoryBackend does NOT have healthcheck."""
        from src.backend.infrastructure.cache.backends.memory import MemoryBackend

        backend = MemoryBackend()
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
        assert cache_a.scope != cache_b.scope

    async def test_no_tag_or_pattern_delete(self) -> None:
        """LruMemoryCache does NOT support tag or pattern deletion."""
        from src.backend.infrastructure.cache.lru_cache import LruMemoryCache

        cache = LruMemoryCache()
        assert not hasattr(cache, "delete_by_tag") or not callable(
            getattr(cache, "delete_by_tag", None)
        )
        assert not hasattr(cache, "delete_pattern") or not callable(
            getattr(cache, "delete_pattern", None)
        )

    async def test_used_by_tier_router(self) -> None:
        """LruMemoryCache is the L1 of infrastructure.ai.semantic_cache.TierRouter."""
        from src.backend.infrastructure.ai.semantic_cache import TierRouter

        class _StubBackend:
            async def get(self, key):
                return None

            async def set(self, key, value, ttl=None):
                pass

        router = TierRouter(l1=None, l2=_StubBackend(), l3=_StubBackend())
        assert router.l1 is not None
        from src.backend.infrastructure.cache.lru_cache import LruMemoryCache

        assert isinstance(router.l1, LruMemoryCache)


class TestTwoClassesHaveDifferentRoles:
    """MemoryBackend (infra) + LruMemoryCache (infra) — DIFFERENT layers."""

    def test_different_base_classes(self) -> None:
        """Каждый класс implements DIFFERENT interface."""
        from src.backend.core.cache.facade import UnifiedCacheFacade
        from src.backend.core.interfaces.cache import CacheBackend
        from src.backend.infrastructure.cache.backends.memory import MemoryBackend
        from src.backend.infrastructure.cache.lru_cache import LruMemoryCache

        # MemoryBackend → CacheBackend interface.
        assert issubclass(MemoryBackend, CacheBackend)
        assert not issubclass(MemoryBackend, UnifiedCacheFacade)

        # LruMemoryCache — duck-typed (no interface inheritance).
        assert not issubclass(LruMemoryCache, CacheBackend)
        assert not issubclass(LruMemoryCache, UnifiedCacheFacade)

    def test_different_type_signatures(self) -> None:
        """Each class has DIFFERENT return type semantics."""
        from src.backend.infrastructure.cache.backends.memory import MemoryBackend
        from src.backend.infrastructure.cache.lru_cache import LruMemoryCache

        backend = MemoryBackend()
        assert "bytes" in str(backend.get.__annotations__.get("return", ""))

        lru = LruMemoryCache()
        assert "Any" in str(lru.get.__annotations__.get("return", ""))


class TestCoreMemoryCacheFacadeRemoved:
    """Cycle 167 (Stage 4): MemoryCacheFacade REMOVED из core.cache.facade."""

    def test_memory_cache_facade_removed_from_core(self) -> None:
        """``MemoryCacheFacade`` больше не доступен в ``core.cache.facade``."""
        import pytest

        with pytest.raises(ImportError):
            exec(  # noqa: S102
                "from src.backend.core.cache.facade import MemoryCacheFacade"
            )

    def test_memory_cache_facade_removed_from_core_cache(self) -> None:
        """``MemoryCacheFacade`` НЕ в ``core.cache.__all__``."""
        from src.backend.core.cache import __all__

        assert "MemoryCacheFacade" not in __all__


class TestNoUnintendedConsolidation:
    """Guards against accidental consolidation."""

    def test_two_classes_are_distinct_objects(self) -> None:
        """Sanity: 2 distinct classes, no aliases."""
        from src.backend.infrastructure.cache.backends.memory import (
            MemoryBackend as MB,
        )
        from src.backend.infrastructure.cache.lru_cache import LruMemoryCache as LMC

        assert MB is not LMC

    def test_import_paths_distinct(self) -> None:
        """Each class lives in a distinct module path."""
        from src.backend.infrastructure.cache.backends.memory import (
            MemoryBackend as MB,
        )
        from src.backend.infrastructure.cache.lru_cache import LruMemoryCache as LMC

        assert MB.__module__ == "src.backend.infrastructure.cache.backends.memory"
        assert LMC.__module__ == "src.backend.infrastructure.cache.lru_cache"