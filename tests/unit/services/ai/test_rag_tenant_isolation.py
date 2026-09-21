"""Sprint 2.6 — L5 RAG/Memory tenant-scope: cross-tenant isolation tests.

Проверяет что :class:`SearchMixin.search` изолирует результаты по
``tenant_id`` при retrieve. Раньше фильтр был только по ``namespace``
(см. pre-change evidence в ``search_mixin.py:114-118``), что давало
tenant-leak при shared namespace.

Контракт:
    * ``tenant_id=None`` + active tenant_scope → фильтр по ContextVar.
    * ``tenant_id="X"`` → фильтр по ``X`` (override context).
    * ``tenant_id=""`` → opt-out, no tenant filter (legacy passthrough).
    * ``tenant_id=None`` + no tenant_scope → no tenant filter (legacy).
    * vector-store ``where`` содержит ``tenant_id`` при активном scope.
    * cache-hit post-filter отрезает чужие chunks (defence-in-depth).
    * два вызова с разными tenant_scope возвращают disjoint результаты.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from src.backend.core.tenancy import TenantContext, tenant_scope
from src.backend.services.ai.rag_service import (
    RAGService,
    _filter_chunks_by_tenant,
    _resolve_effective_tenant_id,
)


class _RecordingStore:
    """Fake BaseVectorStore, запоминает ``where`` для assertions."""

    def __init__(self, *, all_results: list[dict[str, Any]] | None = None) -> None:
        self._all_results = all_results or []
        self.calls: list[dict[str, Any]] = []
        self.upsert = AsyncMock()
        self.delete = AsyncMock()
        self.delete_where = AsyncMock(return_value=1)

    async def query(
        self, *, embedding: list[float], top_k: int, where: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        self.calls.append({"embedding": embedding, "top_k": top_k, "where": where})
        if not where:
            return list(self._all_results)
        return [
            r
            for r in self._all_results
            if all((r.get("metadata") or {}).get(k) == v for k, v in where.items())
        ]


class _FakeEmbedder:
    """Минимальный fake EmbeddingProvider."""

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.1, 0.2, 0.3] for _ in texts]


# ─────────────────────────────────────────────────────────────────────
# Resolution helper unit-tests
# ─────────────────────────────────────────────────────────────────────


def test_resolve_effective_tenant_id_explicit_wins() -> None:
    """Explicit non-empty ``tenant_id`` возвращается as-is."""
    assert _resolve_effective_tenant_id("bank_x") == "bank_x"


def test_resolve_effective_tenant_id_empty_string_is_opt_out() -> None:
    """Explicit ``""`` → None (явный opt-out)."""
    assert _resolve_effective_tenant_id("") is None


def test_resolve_effective_tenant_id_none_falls_back_to_context() -> None:
    """``None`` без context → None (legacy passthrough)."""
    # Никакого tenant_scope — ContextVar возвращает None.
    assert _resolve_effective_tenant_id(None) is None


def test_resolve_effective_tenant_id_none_reads_contextvar() -> None:
    """``None`` внутри tenant_scope → tenant_id из ContextVar."""
    with tenant_scope(TenantContext(tenant_id="bank_a")):
        assert _resolve_effective_tenant_id(None) == "bank_a"


def test_resolve_effective_tenant_id_explicit_overrides_context() -> None:
    """Explicit kwarg приоритетнее ContextVar."""
    with tenant_scope(TenantContext(tenant_id="bank_a")):
        assert _resolve_effective_tenant_id("bank_override") == "bank_override"


# ─────────────────────────────────────────────────────────────────────
# Post-filter helper unit-tests
# ─────────────────────────────────────────────────────────────────────


def test_filter_chunks_by_tenant_passthrough_when_none() -> None:
    """``tenant_id=None`` — passthrough (нет фильтрации)."""
    chunks = [
        {"id": "1", "metadata": {"tenant_id": "bank_a"}},
        {"id": "2", "metadata": {"tenant_id": "bank_b"}},
    ]
    assert _filter_chunks_by_tenant(chunks, None) == chunks


def test_filter_chunks_by_tenant_keeps_matching() -> None:
    """Chunks с matching tenant_id остаются."""
    chunks = [
        {"id": "1", "metadata": {"tenant_id": "bank_a"}},
        {"id": "2", "metadata": {"tenant_id": "bank_b"}},
        {"id": "3", "metadata": {"tenant_id": "bank_a"}},
    ]
    out = _filter_chunks_by_tenant(chunks, "bank_a")
    assert [c["id"] for c in out] == ["1", "3"]


def test_filter_chunks_by_tenant_drops_missing_metadata() -> None:
    """Chunks без ``metadata.tenant_id`` отбрасываются при фильтре."""
    chunks = [
        {"id": "1", "metadata": {"tenant_id": "bank_a"}},
        {"id": "2", "metadata": {}},  # legacy без tenant_id
        {"id": "3"},  # без metadata
    ]
    out = _filter_chunks_by_tenant(chunks, "bank_a")
    assert [c["id"] for c in out] == ["1"]


# ─────────────────────────────────────────────────────────────────────
# SearchMixin integration: cross-tenant isolation
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_search_filters_by_tenant_from_context() -> None:
    """Active tenant_scope → vector-store ``where`` содержит ``tenant_id``."""
    all_chunks: list[dict[str, Any]] = [
        {"id": "a1", "document": "alpha", "metadata": {"tenant_id": "bank_a"}},
        {"id": "a2", "document": "beta", "metadata": {"tenant_id": "bank_a"}},
        {"id": "b1", "document": "gamma", "metadata": {"tenant_id": "bank_b"}},
        {"id": "b2", "document": "delta", "metadata": {"tenant_id": "bank_b"}},
    ]
    store = _RecordingStore(all_results=all_chunks)
    service = RAGService(store=store, embedder=_FakeEmbedder(), cache=None)

    with tenant_scope(TenantContext(tenant_id="bank_a")):
        results = await service.search("query", top_k=10)

    assert {r["id"] for r in results} == {"a1", "a2"}
    # store.query получил ``where`` с tenant_id=bank_a.
    assert len(store.calls) == 1
    assert store.calls[0]["where"] == {"tenant_id": "bank_a"}


@pytest.mark.asyncio
async def test_search_explicit_tenant_id_overrides_context() -> None:
    """Explicit ``tenant_id`` в kwargs перекрывает ContextVar."""
    all_chunks: list[dict[str, Any]] = [
        {"id": "a1", "metadata": {"tenant_id": "bank_a"}},
        {"id": "b1", "metadata": {"tenant_id": "bank_b"}},
    ]
    store = _RecordingStore(all_results=all_chunks)
    service = RAGService(store=store, embedder=_FakeEmbedder(), cache=None)

    with tenant_scope(TenantContext(tenant_id="bank_a")):
        results = await service.search("query", top_k=10, tenant_id="bank_b")

    assert {r["id"] for r in results} == {"b1"}
    assert store.calls[0]["where"] == {"tenant_id": "bank_b"}


@pytest.mark.asyncio
async def test_search_empty_tenant_id_opts_out() -> None:
    """``tenant_id=""`` → фильтр не применяется (legacy)."""
    all_chunks: list[dict[str, Any]] = [
        {"id": "a1", "metadata": {"tenant_id": "bank_a"}},
        {"id": "b1", "metadata": {"tenant_id": "bank_b"}},
    ]
    store = _RecordingStore(all_results=all_chunks)
    service = RAGService(store=store, embedder=_FakeEmbedder(), cache=None)

    # С active context, но явный opt-out → filter не активируется.
    with tenant_scope(TenantContext(tenant_id="bank_a")):
        results = await service.search("query", top_k=10, tenant_id="")

    assert {r["id"] for r in results} == {"a1", "b1"}
    # store.query получил ``where=None`` (passthrough).
    assert store.calls[0]["where"] is None


@pytest.mark.asyncio
async def test_search_no_context_legacy_passthrough() -> None:
    """Без tenant_scope и без explicit → no tenant filter (backward-compat)."""
    all_chunks: list[dict[str, Any]] = [
        {"id": "a1", "metadata": {"tenant_id": "bank_a"}},
        {"id": "b1", "metadata": {"tenant_id": "bank_b"}},
    ]
    store = _RecordingStore(all_results=all_chunks)
    service = RAGService(store=store, embedder=_FakeEmbedder(), cache=None)

    results = await service.search("query", top_k=10)

    assert {r["id"] for r in results} == {"a1", "b1"}
    assert store.calls[0]["where"] is None


@pytest.mark.asyncio
async def test_search_where_combines_namespace_and_tenant() -> None:
    """``namespace`` + ``tenant_id`` оба попадают в compound where."""
    all_chunks: list[dict[str, Any]] = [
        {"id": "match", "metadata": {"namespace": "docs", "tenant_id": "bank_a"}},
        {"id": "wrong-ns", "metadata": {"namespace": "other", "tenant_id": "bank_a"}},
        {
            "id": "wrong-tenant",
            "metadata": {"namespace": "docs", "tenant_id": "bank_b"},
        },
    ]
    store = _RecordingStore(all_results=all_chunks)
    service = RAGService(store=store, embedder=_FakeEmbedder(), cache=None)

    with tenant_scope(TenantContext(tenant_id="bank_a")):
        results = await service.search("query", top_k=10, namespace="docs")

    assert {r["id"] for r in results} == {"match"}
    assert store.calls[0]["where"] == {"namespace": "docs", "tenant_id": "bank_a"}


@pytest.mark.asyncio
async def test_search_cross_tenant_isolation_end_to_end() -> None:
    """Tenant A и Tenant B видят disjoint chunks в одном namespace."""
    all_chunks: list[dict[str, Any]] = [
        {"id": "a1", "metadata": {"tenant_id": "bank_a", "namespace": "shared"}},
        {"id": "a2", "metadata": {"tenant_id": "bank_a", "namespace": "shared"}},
        {"id": "b1", "metadata": {"tenant_id": "bank_b", "namespace": "shared"}},
        {"id": "b2", "metadata": {"tenant_id": "bank_b", "namespace": "shared"}},
    ]
    store = _RecordingStore(all_results=all_chunks)
    service = RAGService(store=store, embedder=_FakeEmbedder(), cache=None)

    # Tenant A.
    with tenant_scope(TenantContext(tenant_id="bank_a")):
        results_a = await service.search("query", namespace="shared")
    # Tenant B.
    with tenant_scope(TenantContext(tenant_id="bank_b")):
        results_b = await service.search("query", namespace="shared")

    ids_a = {r["id"] for r in results_a}
    ids_b = {r["id"] for r in results_b}

    assert ids_a == {"a1", "a2"}
    assert ids_b == {"b1", "b2"}
    # Disjoint.
    assert ids_a.isdisjoint(ids_b)
    # Оба вызова — это два разных where-фильтра.
    assert len(store.calls) == 2
    assert store.calls[0]["where"] == {"namespace": "shared", "tenant_id": "bank_a"}
    assert store.calls[1]["where"] == {"namespace": "shared", "tenant_id": "bank_b"}


@pytest.mark.asyncio
async def test_search_post_filters_store_results() -> None:
    """Backend без where-filter (FAISS-like) — post-filter всё равно изолирует.

    Симулируем backend, который игнорирует ``where`` и возвращает
    чужие chunks — ``_filter_chunks_by_tenant`` обязан их отрезать.
    """
    all_chunks: list[dict[str, Any]] = [
        {"id": "a1", "metadata": {"tenant_id": "bank_a"}},
        {"id": "b1", "metadata": {"tenant_id": "bank_b"}},  # leaked
        {"id": "a2", "metadata": {"tenant_id": "bank_a"}},
    ]

    class _NaiveStore(_RecordingStore):
        async def query(
            self,
            *,
            embedding: list[float],
            top_k: int,
            where: dict[str, Any] | None = None,
        ) -> list[dict[str, Any]]:
            # Игнорируем where — как FAISSVectorStore в текущей реализации.
            await super().query(embedding=embedding, top_k=top_k, where=where)
            return list(self._all_results)

    store = _NaiveStore(all_results=all_chunks)
    service = RAGService(store=store, embedder=_FakeEmbedder(), cache=None)

    with tenant_scope(TenantContext(tenant_id="bank_a")):
        results = await service.search("query", top_k=10)

    assert {r["id"] for r in results} == {"a1", "a2"}


# ─────────────────────────────────────────────────────────────────────
# Cache-hit post-filter
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_search_cache_hit_drops_cross_tenant_chunks() -> None:
    """Cache-hit, содержащий чужие chunks, post-filter отрезает их.

    Сценарий: cache был положен с tenant=B (cache-key по namespace only),
    tenant=A делает lookup того же namespace — без post-filter получил бы
    чужой контент. Defence-in-depth через ``_filter_chunks_by_tenant``.
    """
    cross_tenant_cached: list[dict[str, Any]] = [
        {"id": "a1", "document": "alpha", "metadata": {"tenant_id": "bank_a"}},
        {"id": "b1", "document": "B-leak", "metadata": {"tenant_id": "bank_b"}},
    ]

    cache = type("C", (), {})()
    cache.lookup_chunks = AsyncMock(return_value=(cross_tenant_cached, "l3"))
    cache.lookup_answer = AsyncMock(return_value=(None, None))
    cache.store_chunks = AsyncMock()
    cache.store_answer = AsyncMock()
    cache.invalidate_by_tag = AsyncMock(return_value=1)

    # store не должен быть вызван: cache-hit + post-filter даёт 1 chunk.
    store = _RecordingStore(all_results=[])
    service = RAGService(store=store, embedder=_FakeEmbedder(), cache=cache)

    with tenant_scope(TenantContext(tenant_id="bank_a")):
        results = await service.search("query", namespace="shared")

    assert {r["id"] for r in results} == {"a1"}
    # store не дёргался (cache вернул non-empty до фильтрации).
    assert store.calls == []


@pytest.mark.asyncio
async def test_search_cache_hit_empty_after_filter_falls_through() -> None:
    """Если cache-hit полностью отфильтрован — fall through в vector store.

    Защита от ситуации, когда cache содержит ТОЛЬКО чужие chunks и
    tenant-context пустой — не возвращаем пустой массив как 200, а
    пробуем vector store (там тоже могут быть пустые результаты,
    но хотя бы не silent-leak).
    """
    only_foreign: list[dict[str, Any]] = [
        {"id": "b1", "metadata": {"tenant_id": "bank_b", "namespace": "shared"}}
    ]
    store_results: list[dict[str, Any]] = [
        {"id": "a1", "metadata": {"tenant_id": "bank_a", "namespace": "shared"}}
    ]
    cache = type("C", (), {})()
    cache.lookup_chunks = AsyncMock(return_value=(only_foreign, "l3"))
    cache.lookup_answer = AsyncMock(return_value=(None, None))
    cache.store_chunks = AsyncMock()
    cache.store_answer = AsyncMock()
    cache.invalidate_by_tag = AsyncMock(return_value=1)

    store = _RecordingStore(all_results=store_results)
    service = RAGService(store=store, embedder=_FakeEmbedder(), cache=cache)

    with tenant_scope(TenantContext(tenant_id="bank_a")):
        results = await service.search("query", namespace="shared")

    assert {r["id"] for r in results} == {"a1"}
    # Fall-through сработал: store.query был вызван.
    assert len(store.calls) == 1
    assert store.calls[0]["where"] == {"namespace": "shared", "tenant_id": "bank_a"}


@pytest.mark.asyncio
async def test_search_passes_tenant_to_cache_lookup_and_store() -> None:
    """Cache.lookup_chunks / store_chunks получают ``tenant`` kwarg.

    Это обеспечивает tenant-scoped ключи в L3 cache (Sprint 2.1) и
    изоляцию на уровне ключа, без зависимости от post-filter.
    """
    cache = type("C", (), {})()
    cache.lookup_chunks = AsyncMock(return_value=(None, None))
    cache.lookup_answer = AsyncMock(return_value=(None, None))
    cache.store_chunks = AsyncMock()
    cache.store_answer = AsyncMock()
    cache.invalidate_by_tag = AsyncMock(return_value=1)

    store_results: list[dict[str, Any]] = [
        {"id": "a1", "metadata": {"tenant_id": "bank_a", "namespace": "shared"}}
    ]
    store = _RecordingStore(all_results=store_results)
    service = RAGService(store=store, embedder=_FakeEmbedder(), cache=cache)

    with tenant_scope(TenantContext(tenant_id="bank_a")):
        await service.search("query", namespace="shared")

    # Cache получил tenant_id из ContextVar.
    cache.lookup_chunks.assert_awaited_once_with(
        "query", tenant="bank_a", namespace="shared"
    )
    cache.store_chunks.assert_awaited_once()
    call = cache.store_chunks.await_args
    assert call is not None
    assert call.kwargs.get("tenant") == "bank_a"
    assert call.kwargs.get("namespace") == "shared"


@pytest.mark.asyncio
async def test_search_passes_explicit_tenant_id_to_cache() -> None:
    """Explicit ``tenant_id`` kwarg пробрасывается в cache (override ContextVar)."""
    cache = type("C", (), {})()
    cache.lookup_chunks = AsyncMock(return_value=(None, None))
    cache.lookup_answer = AsyncMock(return_value=(None, None))
    cache.store_chunks = AsyncMock()
    cache.store_answer = AsyncMock()
    cache.invalidate_by_tag = AsyncMock(return_value=1)

    store = _RecordingStore(
        all_results=[{"id": "x", "metadata": {"tenant_id": "override"}}]
    )
    service = RAGService(store=store, embedder=_FakeEmbedder(), cache=cache)

    with tenant_scope(TenantContext(tenant_id="bank_a")):
        await service.search("query", tenant_id="override")

    cache.lookup_chunks.assert_awaited_once_with(
        "query", tenant="override", namespace=None
    )


@pytest.mark.asyncio
async def test_search_passes_none_tenant_to_cache_when_no_context() -> None:
    """Без tenant_scope и без explicit kwarg — cache получает ``tenant=None``.

    L3 cache интерпретирует ``None`` как ``_unscoped_`` sentinel
    (consistent с TenantCacheBackend).
    """
    cache = type("C", (), {})()
    cache.lookup_chunks = AsyncMock(return_value=(None, None))
    cache.lookup_answer = AsyncMock(return_value=(None, None))
    cache.store_chunks = AsyncMock()
    cache.store_answer = AsyncMock()
    cache.invalidate_by_tag = AsyncMock(return_value=1)

    store = _RecordingStore(all_results=[{"id": "x", "metadata": {}}])
    service = RAGService(store=store, embedder=_FakeEmbedder(), cache=cache)

    # Без tenant_scope.
    await service.search("query")

    cache.lookup_chunks.assert_awaited_once_with("query", tenant=None, namespace=None)
