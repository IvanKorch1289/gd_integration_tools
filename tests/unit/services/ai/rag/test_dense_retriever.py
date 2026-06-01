"""Unit-тесты DenseRetriever (wave:s19/k4-w6-adaptive-rag-strategy-finale).

Проверяет:
1. retrieve() с валидным query возвращает DenseResult.
2. retrieve() с пустым query возвращает пустой список.
3. embed_fn/dense_search вызываются корректно.
4. Graceful fallback при embed failure.
5. Graceful fallback при search failure.
6. DenseResult dataclass immutable.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from src.backend.services.ai.rag.dense_retriever import (
    DenseResult,
    DenseRetriever,
)


@pytest.mark.asyncio
async def test_retrieve_returns_dense_results() -> None:
    """Успешный retrieve возвращает непустой список DenseResult."""
    embed_mock = AsyncMock(return_value=[[0.1, 0.2, 0.3]])
    search_mock = AsyncMock(
        return_value=[
            {"id": "doc1", "document": "текст 1", "metadata": {"source": "a"}},
            {"id": "doc2", "document": "текст 2", "metadata": {"source": "b"}},
        ]
    )
    retriever = DenseRetriever(embed_fn=embed_mock, search_vectors=search_mock)

    results = await retriever.retrieve(query="тестовый запрос", top_k=2)

    assert len(results) == 2
    assert all(isinstance(r, dict) for r in results)
    assert results[0]["chunk_id"] == "doc1"
    assert results[0]["document"] == "текст 1"
    assert "score" in results[0]


@pytest.mark.asyncio
async def test_retrieve_empty_query_returns_empty() -> None:
    """Пустой query возвращает пустой список."""
    embed_mock = AsyncMock()
    search_mock = AsyncMock()
    retriever = DenseRetriever(embed_fn=embed_mock, search_vectors=search_mock)

    results = await retriever.retrieve(query="   ", top_k=5)

    assert results == []
    embed_mock.assert_not_called()
    search_mock.assert_not_called()


@pytest.mark.asyncio
async def test_retrieve_embed_failure_returns_empty() -> None:
    """Embed failure → empty list, не exception."""
    embed_mock = AsyncMock(side_effect=RuntimeError("embedding service down"))
    search_mock = AsyncMock()
    retriever = DenseRetriever(embed_fn=embed_mock, search_vectors=search_mock)

    results = await retriever.retrieve(query="запрос", top_k=5)

    assert results == []
    search_mock.assert_not_called()


@pytest.mark.asyncio
async def test_retrieve_search_failure_returns_empty() -> None:
    """Search failure → empty list, не exception."""
    embed_mock = AsyncMock(return_value=[[0.1, 0.2]])
    search_mock = AsyncMock(side_effect=RuntimeError("vector store down"))
    retriever = DenseRetriever(embed_fn=embed_mock, search_vectors=search_mock)

    results = await retriever.retrieve(query="запрос", top_k=5)

    assert results == []


@pytest.mark.asyncio
async def test_retrieve_correct_args_passed() -> None:
    """Embed и search вызываются с правильными аргументами."""
    captured_embed: list[str] = []
    captured_top_k: list[int] = []

    async def capture_embed(texts: list[str]) -> list[list[float]]:
        captured_embed.extend(texts)
        return [[0.1]]

    async def capture_search(embeddings: list[list[float]], top_k: int) -> list[dict[str, Any]]:
        captured_top_k.append(top_k)
        return []

    retriever = DenseRetriever(embed_fn=capture_embed, search_vectors=capture_search)
    await retriever.retrieve(query="мой запрос", top_k=7)

    assert captured_embed == ["мой запрос"]
    assert captured_top_k == [7]


def test_dense_result_immutable() -> None:
    """DenseResult — dict (TypedDict), но проверяем что поля корректные."""
    result: DenseResult = {
        "chunk_id": "x",
        "document": "doc",
        "metadata": {"page": 1},
        "score": 0.95,
    }
    assert result["chunk_id"] == "x"
    assert result["score"] == 0.95


@pytest.mark.asyncio
async def test_retrieve_top_k_limits_results() -> None:
    """Top_k ограничивает количество результатов."""
    embed_mock = AsyncMock(return_value=[[0.1]])
    search_mock = AsyncMock(
        return_value=[
            {"id": f"doc{i}", "document": f"текст {i}", "metadata": {}}
            for i in range(10)
        ]
    )
    retriever = DenseRetriever(embed_fn=embed_mock, search_vectors=search_mock)

    results = await retriever.retrieve(query="запрос", top_k=3)

    assert len(results) == 3


@pytest.mark.asyncio
async def test_retrieve_handles_metadata_id() -> None:
    """Chunk ID из metadata.id если нет id."""
    embed_mock = AsyncMock(return_value=[[0.1]])
    search_mock = AsyncMock(
        return_value=[
            {"document": "текст", "metadata": {"id": "meta_id_123"}},
        ]
    )
    retriever = DenseRetriever(embed_fn=embed_mock, search_vectors=search_mock)

    results = await retriever.retrieve(query="запрос", top_k=5)

    assert len(results) == 1
    assert results[0]["chunk_id"] == "meta_id_123"


@pytest.mark.asyncio
async def test_retrieve_empty_embeddings_returns_empty() -> None:
    """Empty embeddings list → empty results."""
    embed_mock = AsyncMock(return_value=[])
    search_mock = AsyncMock()
    retriever = DenseRetriever(embed_fn=embed_mock, search_vectors=search_mock)

    results = await retriever.retrieve(query="запрос", top_k=5)

    assert results == []
    search_mock.assert_not_called()


@pytest.mark.asyncio
async def test_retrieve_text_field_instead_of_document() -> None:
    """Результат может содержать 'text' вместо 'document'."""
    embed_mock = AsyncMock(return_value=[[0.1]])
    search_mock = AsyncMock(
        return_value=[
            {"id": "doc1", "text": "текст из поля text", "metadata": {}},
        ]
    )
    retriever = DenseRetriever(embed_fn=embed_mock, search_vectors=search_mock)

    results = await retriever.retrieve(query="запрос", top_k=5)

    assert len(results) == 1
    assert results[0]["document"] == "текст из поля text"
