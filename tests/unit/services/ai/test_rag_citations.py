"""Тесты Stream E.5 — RAG citations в ``augment_prompt_with_citations``."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from src.backend.services.ai.rag_service import (
    AugmentResult,
    RAGCitation,
    RAGService,
)


def _make_store(hits: list[dict[str, Any]]) -> Any:
    """Создаёт mock-vector-store, чей ``query`` возвращает заранее заданные hits."""
    store = type("S", (), {})()
    store.query = AsyncMock(return_value=hits)
    store.upsert = AsyncMock()
    store.delete = AsyncMock()
    store.count = AsyncMock(return_value=0)
    return store


def _make_embedder() -> Any:
    e = type("E", (), {})()
    e.embed = AsyncMock(return_value=[[0.1, 0.2, 0.3]])
    return e


@pytest.mark.asyncio
async def test_augment_with_citations_returns_three_items() -> None:
    """Три результата → три citation в ответе с правильными source_doc/chunk_id/score."""
    hits = [
        {
            "id": "doc1_chunk_0",
            "document": "Первый chunk про авторизацию",
            "metadata": {
                "source": "auth-guide.md",
                "doc_id": "doc1",
                "chunk_idx": 0,
                "namespace": "kb",
            },
            "distance": 0.12,
        },
        {
            "id": "doc1_chunk_1",
            "document": "Второй chunk про токены",
            "metadata": {
                "source": "auth-guide.md",
                "doc_id": "doc1",
                "chunk_idx": 1,
                "namespace": "kb",
            },
            "distance": 0.18,
        },
        {
            "id": "doc2_chunk_0",
            "document": "Третий chunk про refresh",
            "metadata": {
                "source": "refresh-flow.md",
                "doc_id": "doc2",
                "chunk_idx": 0,
                "namespace": "kb",
            },
            "distance": 0.31,
        },
    ]
    rag = RAGService(store=_make_store(hits), embedder=_make_embedder())

    result = await rag.augment_prompt_with_citations(
        query="как работает refresh-токен?",
        system_prompt="Ты эксперт по auth.",
        top_k=3,
        namespace="kb",
    )

    assert isinstance(result, AugmentResult)
    assert "Контекст из базы знаний" in result.prompt
    assert "refresh-токен" in result.prompt
    assert len(result.citations) == 3
    cit = result.citations[0]
    assert isinstance(cit, RAGCitation)
    assert cit.source_doc == "auth-guide.md"
    assert cit.chunk_id == "doc1_chunk_0"
    assert cit.score == pytest.approx(0.12)
    assert cit.chunk_idx == 0
    assert cit.namespace == "kb"
    assert result.citations[2].source_doc == "refresh-flow.md"


@pytest.mark.asyncio
async def test_augment_no_hits_returns_empty_citations() -> None:
    """Пустой результат поиска → citations=[] и prompt без context-секции."""
    rag = RAGService(store=_make_store([]), embedder=_make_embedder())

    result = await rag.augment_prompt_with_citations(
        query="вопрос без контекста",
        system_prompt="Ты помощник.",
        top_k=5,
    )
    assert result.citations == []
    assert "Контекст из базы знаний" not in result.prompt
    assert "вопрос без контекста" in result.prompt


@pytest.mark.asyncio
async def test_augment_fallback_doc_id_when_source_missing() -> None:
    """source отсутствует → source_doc берётся из doc_id; score=0 при отсутствии distance."""
    hits = [
        {
            "id": "X_chunk_0",
            "document": "raw content",
            "metadata": {"doc_id": "X", "chunk_idx": 0, "namespace": "default"},
        },
    ]
    rag = RAGService(store=_make_store(hits), embedder=_make_embedder())

    result = await rag.augment_prompt_with_citations(query="q", top_k=1)
    assert len(result.citations) == 1
    cit = result.citations[0]
    assert cit.source_doc == "X"
    assert cit.score == 0.0
    assert cit.chunk_id == "X_chunk_0"


@pytest.mark.asyncio
async def test_augment_prompt_str_form_backwards_compat() -> None:
    """Backward-compat: ``augment_prompt`` возвращает str (без citations)."""
    hits = [
        {
            "id": "d_chunk_0",
            "document": "context piece",
            "metadata": {"doc_id": "d", "chunk_idx": 0, "namespace": "ns"},
            "distance": 0.5,
        },
    ]
    rag = RAGService(store=_make_store(hits), embedder=_make_embedder())

    out = await rag.augment_prompt(query="q1", system_prompt="sys", top_k=1)
    assert isinstance(out, str)
    assert "Контекст из базы знаний" in out
    assert "context piece" in out
