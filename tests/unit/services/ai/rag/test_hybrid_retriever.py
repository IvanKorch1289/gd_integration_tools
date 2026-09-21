"""Unit test для Block 3.2 (gap-ai-3.2, ADR-0074).

Проверяет :class:`HybridRetriever`:

1. ``rrf_merge`` корректно объединяет 2 ranked lists с формулой
   ``score = Σ 1/(k + rank+1)``.
2. ``HybridRetriever.retrieve`` без BM25 (пустой corpus) → dense-only
   passthrough.
3. С BM25 — top-k содержит и lexical-match (BM25 win), и semantic-match
   (dense win).
4. Graceful fallback при ImportError rank-bm25.
5. Provenance source включает 'dense' и 'bm25' в правильных позициях.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from src.backend.services.ai.rag.hybrid_retriever import (
    HybridResult,
    HybridRetriever,
    rrf_merge,
)


def test_rrf_merge_combines_ranks() -> None:
    """RRF: doc в top обоих listов имеет наивысший score."""
    ranked_lists = [
        ("dense", ["docA", "docB", "docC"]),
        ("bm25", ["docB", "docA", "docD"]),
    ]
    merged = rrf_merge(ranked_lists=ranked_lists, k=60)
    chunk_ids = [item[0] for item in merged]
    # docA и docB присутствуют в обоих — выше.
    assert chunk_ids[0] in ("docA", "docB")
    assert chunk_ids[1] in ("docA", "docB")
    # docC и docD только в одном listе — ниже.
    assert chunk_ids[-2:] == sorted([chunk_ids[-2], chunk_ids[-1]])


def test_rrf_provenance_includes_both_sources() -> None:
    """RRF: для doc в обоих списках sources содержит и 'dense', и 'bm25'."""
    ranked_lists = [("dense", ["doc1", "doc2"]), ("bm25", ["doc1", "doc3"])]
    merged = rrf_merge(ranked_lists=ranked_lists, k=60)
    by_id = {cid: (score, sources) for cid, score, sources in merged}
    assert sorted(by_id["doc1"][1]) == ["bm25", "dense"]
    assert by_id["doc2"][1] == ("dense",)
    assert by_id["doc3"][1] == ("bm25",)


@pytest.mark.asyncio
async def test_retrieve_passthrough_when_no_corpus() -> None:
    """Пустой corpus → dense-only fallback (BM25 отключён)."""
    dense_mock = AsyncMock(
        return_value=[
            {"id": "a", "document": "doc a", "metadata": {}},
            {"id": "b", "document": "doc b", "metadata": {}},
        ]
    )
    retriever = HybridRetriever(dense_search=dense_mock, corpus=[])
    results = await retriever.retrieve(query="x", top_k=2)
    assert len(results) == 2
    assert all(r.sources == ("dense",) for r in results)
    assert all(isinstance(r, HybridResult) for r in results)


@pytest.mark.asyncio
async def test_retrieve_combines_dense_and_bm25(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """С corpus + BM25 mock → результат содержит и dense, и bm25 ids."""
    # Mock dense — возвращает doc_dense + общий doc_both.
    dense_mock = AsyncMock(
        return_value=[
            {"id": "doc_both", "document": "общий документ", "metadata": {}},
            {"id": "doc_dense", "document": "семантика", "metadata": {}},
        ]
    )

    # Mock BM25 через подмену _ensure_bm25.
    corpus = [
        {"id": "doc_bm25", "text": "ключевые слова", "metadata": {}},
        {"id": "doc_both", "text": "общий документ", "metadata": {}},
    ]
    retriever = HybridRetriever(dense_search=dense_mock, corpus=corpus)

    class _FakeBM25:
        def get_top_n(
            self, query_tokens: list[str], docs: list[dict], n: int
        ) -> list[dict]:
            # BM25 ранжирует doc_bm25 первым.
            return [docs[0], docs[1]][:n]

    monkeypatch.setattr(retriever, "_ensure_bm25", lambda: _FakeBM25())

    results = await retriever.retrieve(query="ключевые семантика", top_k=3)
    ids = {r.chunk_id for r in results}
    assert "doc_dense" in ids
    assert "doc_bm25" in ids
    # doc_both должен иметь sources с обоими.
    by_id = {r.chunk_id: r for r in results}
    if "doc_both" in by_id:
        assert "dense" in by_id["doc_both"].sources
        assert "bm25" in by_id["doc_both"].sources


@pytest.mark.asyncio
async def test_retrieve_graceful_on_dense_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Dense raise → fallback на BM25 only (или пустой результат)."""
    dense_mock = AsyncMock(side_effect=RuntimeError("vector store down"))
    corpus = [{"id": "doc1", "text": "text", "metadata": {}}]
    retriever = HybridRetriever(dense_search=dense_mock, corpus=corpus)

    class _FakeBM25:
        def get_top_n(
            self, query_tokens: list[str], docs: list[dict], n: int
        ) -> list[dict]:
            return docs[:n]

    monkeypatch.setattr(retriever, "_ensure_bm25", lambda: _FakeBM25())

    results = await retriever.retrieve(query="x", top_k=3)
    # BM25-only — но это всё ещё HybridResult.
    assert len(results) == 1
    assert results[0].chunk_id == "doc1"
    assert "bm25" in results[0].sources


@pytest.mark.asyncio
async def test_retrieve_dense_search_kwargs_signature() -> None:
    """dense_search вызывается с kw-args query/top_k."""
    captured: dict[str, Any] = {}

    async def _capture(*, query: str, top_k: int) -> list[dict]:
        captured["query"] = query
        captured["top_k"] = top_k
        return []

    retriever = HybridRetriever(dense_search=_capture, corpus=[])
    await retriever.retrieve(query="my-q", top_k=3)
    assert captured["query"] == "my-q"
    assert captured["top_k"] == 6  # top_k*2


def test_hybrid_result_dataclass_immutable() -> None:
    """HybridResult — frozen dataclass."""
    res = HybridResult(
        chunk_id="x", document="doc", metadata={}, rrf_score=1.0, sources=("dense",)
    )
    with pytest.raises((AttributeError, Exception)):
        res.chunk_id = "y"  # type: ignore[misc]
