"""Интеграционные тесты RAGService ↔ ThreeTierRagCache (D.1).

Покрывает 5 кейсов:

1. L1 answer-hit → RAG.augment_prompt сразу возвращает кэш.
2. L3 retrieval-hit → RAG.search возвращает чанки без обращения к store.
3. cache=None → passthrough (без падений).
4. ingest/delete_collection → invalidate_by_tag вызван.
5. augment_prompt MISS → результат пишется в L1/L2.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from src.backend.services.ai.rag_service import RAGService


class _FakeStore:
    """Минимальный async fake BaseVectorStore."""

    def __init__(self, *, query_result: list[dict[str, Any]] | None = None) -> None:
        self.query_result = query_result or [
            {"document": "ctx-1", "score": 0.9, "metadata": {"doc_id": "d1", "chunk_idx": 0}}
        ]
        self.upsert = AsyncMock()
        self.delete = AsyncMock()
        self.delete_where = AsyncMock(return_value=1)

    async def query(
        self, *, embedding: list[float], top_k: int, where: dict | None = None
    ) -> list[dict[str, Any]]:
        return self.query_result


class _FakeEmbedder:
    """Минимальный fake EmbeddingProvider."""

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.1, 0.2, 0.3] for _ in texts]


def _make_cache(
    *,
    l1_answer: Any = None,
    l3_chunks: list[dict[str, Any]] | None = None,
) -> Any:
    cache = type("C", (), {})()
    cache.lookup_answer = AsyncMock(
        return_value=(l1_answer, "l1" if l1_answer is not None else None)
    )
    cache.lookup_chunks = AsyncMock(
        return_value=(l3_chunks, "l3" if l3_chunks is not None else None)
    )
    cache.store_answer = AsyncMock()
    cache.store_chunks = AsyncMock()
    cache.invalidate_by_tag = AsyncMock(return_value=1)
    return cache


@pytest.mark.asyncio
async def test_augment_prompt_l1_hit_short_circuits() -> None:
    cache = _make_cache(l1_answer="кэшированный prompt")
    service = RAGService(store=_FakeStore(), embedder=_FakeEmbedder(), cache=cache)
    result = await service.augment_prompt("вопрос", namespace="ns")
    assert result == "кэшированный prompt"
    cache.lookup_answer.assert_awaited_once()


@pytest.mark.asyncio
async def test_search_l3_hit_skips_store() -> None:
    chunks = [{"document": "cached-chunk", "score": 0.95}]
    cache = _make_cache(l3_chunks=chunks)
    store = _FakeStore()
    service = RAGService(store=store, embedder=_FakeEmbedder(), cache=cache)
    result = await service.search("вопрос", namespace="ns")
    assert result == chunks
    cache.lookup_chunks.assert_awaited_once()


@pytest.mark.asyncio
async def test_passthrough_without_cache() -> None:
    store = _FakeStore()
    service = RAGService(store=store, embedder=_FakeEmbedder(), cache=None)
    result = await service.search("q")
    assert result == store.query_result


@pytest.mark.asyncio
async def test_delete_collection_invalidates_tag() -> None:
    cache = _make_cache()
    service = RAGService(store=_FakeStore(), embedder=_FakeEmbedder(), cache=cache)
    await service.delete_collection("ns-x")
    cache.invalidate_by_tag.assert_awaited_with("namespace:ns-x")


@pytest.mark.asyncio
async def test_augment_prompt_miss_stores_to_cache() -> None:
    cache = _make_cache()
    service = RAGService(store=_FakeStore(), embedder=_FakeEmbedder(), cache=cache)
    result = await service.augment_prompt(
        "новый вопрос", system_prompt="SP", top_k=3, namespace="ns"
    )
    assert "новый вопрос" in result
    cache.store_chunks.assert_awaited_once()
    cache.store_answer.assert_awaited_once()
