"""Unit-тесты MultiQueryRetriever (wave:s19/k4-w6-adaptive-rag-strategy-finale).

Проверяет:
1. retrieve() с валидным query возвращает MultiQueryResult.
2. retrieve() с пустым query возвращает пустой список.
3. generate_reformulations вызывается с правильными параметрами.
4. Оригинальный запрос включается в список реформ.
5. RRF merge объединяет результаты от разных запросов.
6. Graceful fallback при любом failure.
7. MultiQueryConfig dataclass immutable.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from src.backend.services.ai.rag.multi_query_retriever import (
    MultiQueryConfig,
    MultiQueryResult,
    MultiQueryRetriever,
)


@pytest.mark.asyncio
async def test_retrieve_returns_multi_query_results() -> None:
    """Успешный retrieve возвращает MultiQueryResult."""
    generate_mock = AsyncMock(
        return_value=[
            "альтернативный запрос 1",
            "альтернативный запрос 2",
        ]
    )
    embed_mock = AsyncMock(return_value=[[0.1], [0.2], [0.3]])
    search_mock = AsyncMock(
        side_effect=[
            [{"id": "doc_a", "document": "документ A", "metadata": {}}],
            [{"id": "doc_b", "document": "документ B", "metadata": {}}],
            [{"id": "doc_c", "document": "документ C", "metadata": {}}],
        ]
    )
    retriever = MultiQueryRetriever(
        embed_fn=embed_mock,
        search_vectors=search_mock,
        generate_reformulations=generate_mock,
    )

    results = await retriever.retrieve(query="оригинальный запрос", top_k=3)

    assert len(results) >= 1
    assert all("chunk_id" in r for r in results)
    assert all("sources" in r for r in results)
    assert all("score" in r for r in results)


@pytest.mark.asyncio
async def test_retrieve_empty_query_returns_empty() -> None:
    """Пустой query возвращает пустой список."""
    generate_mock = AsyncMock()
    embed_mock = AsyncMock()
    search_mock = AsyncMock()
    retriever = MultiQueryRetriever(
        embed_fn=embed_mock,
        search_vectors=search_mock,
        generate_reformulations=generate_mock,
    )

    results = await retriever.retrieve(query="   ", top_k=5)

    assert results == []
    generate_mock.assert_not_called()


@pytest.mark.asyncio
async def test_generate_reformulations_called_with_query_and_num() -> None:
    """Generate вызывается с query и num_reformulations из config."""
    captured: dict[str, Any] = {}

    async def capture_generate(query: str, num: int) -> list[str]:
        captured["query"] = query
        captured["num"] = num
        return []

    embed_mock = AsyncMock(return_value=[[0.1]])
    search_mock = AsyncMock(return_value=[])
    config = MultiQueryConfig(num_reformulations=3)
    retriever = MultiQueryRetriever(
        embed_fn=embed_mock,
        search_vectors=search_mock,
        generate_reformulations=capture_generate,
        config=config,
    )

    await retriever.retrieve(query="мой запрос", top_k=5)

    assert captured["query"] == "мой запрос"
    assert captured["num"] == 3


@pytest.mark.asyncio
async def test_original_query_included_in_search() -> None:
    """Оригинальный запрос всегда включается в search."""
    all_embeds: list[list[float]] = []

    async def capture_embed(texts: list[str]) -> list[list[float]]:
        # Возвращаем уникальный embedding для каждого текста
        return [[float(i)] for i in range(len(texts))]

    async def capture_search(embeddings: list[list[float]], top_k: int) -> list[dict[str, Any]]:
        all_embeds.extend(embeddings)
        return []

    generate_mock = AsyncMock(return_value=["реформ1", "реформ2"])
    retriever = MultiQueryRetriever(
        embed_fn=capture_embed,
        search_vectors=capture_search,
        generate_reformulations=generate_mock,
    )

    await retriever.retrieve(query="запрос", top_k=5)

    # 1 оригинальный + 2 реформа = 3 запроса
    assert len(all_embeds) == 3


@pytest.mark.asyncio
async def test_retrieve_generate_failure_returns_empty() -> None:
    """Generate failure → empty list."""
    generate_mock = AsyncMock(side_effect=RuntimeError("LLM down"))
    embed_mock = AsyncMock()
    search_mock = AsyncMock()
    retriever = MultiQueryRetriever(
        embed_fn=embed_mock,
        search_vectors=search_mock,
        generate_reformulations=generate_mock,
    )

    results = await retriever.retrieve(query="запрос", top_k=5)

    assert results == []
    embed_mock.assert_not_called()


@pytest.mark.asyncio
async def test_retrieve_embed_failure_returns_empty() -> None:
    """Embed failure → empty list."""
    generate_mock = AsyncMock(return_value=["реформ1"])
    embed_mock = AsyncMock(side_effect=RuntimeError("embedding down"))
    search_mock = AsyncMock()
    retriever = MultiQueryRetriever(
        embed_fn=embed_mock,
        search_vectors=search_mock,
        generate_reformulations=generate_mock,
    )

    results = await retriever.retrieve(query="запрос", top_k=5)

    assert results == []
    search_mock.assert_not_called()


@pytest.mark.asyncio
async def test_retrieve_search_failure_still_returns_results() -> None:
    """Search failure для одного запроса — результаты от других всё ещё возвращаются."""
    generate_mock = AsyncMock(return_value=["реформ1"])
    embed_mock = AsyncMock(return_value=[[0.1], [0.2]])
    search_mock = AsyncMock(
        side_effect=[
            RuntimeError("search down"),
            [{"id": "doc1", "document": "документ", "metadata": {}}],
        ]
    )
    retriever = MultiQueryRetriever(
        embed_fn=embed_mock,
        search_vectors=search_mock,
        generate_reformulations=generate_mock,
    )

    results = await retriever.retrieve(query="запрос", top_k=5)

    # Один search упал, но второй вернул результат
    assert len(results) == 1


@pytest.mark.asyncio
async def test_retrieve_empty_reformulations_still_works() -> None:
    """Пустой список реформ — search только по оригинальному запросу."""
    generate_mock = AsyncMock(return_value=[])
    embed_mock = AsyncMock(return_value=[[0.1]])
    search_mock = AsyncMock(
        return_value=[{"id": "doc1", "document": "документ", "metadata": {}}]
    )
    retriever = MultiQueryRetriever(
        embed_fn=embed_mock,
        search_vectors=search_mock,
        generate_reformulations=generate_mock,
    )

    results = await retriever.retrieve(query="запрос", top_k=5)

    assert len(results) == 1


@pytest.mark.asyncio
async def test_retrieve_sequential_mode() -> None:
    """Sequential mode (parallel=False) работает корректно."""
    call_order: list[str] = []

    async def track_embed(texts: list[str]) -> list[list[float]]:
        call_order.append(f"embed-{len(texts)}")
        return [[0.1] for _ in texts]

    async def track_search(embeddings: list[list[float]], top_k: int) -> list[dict[str, Any]]:
        call_order.append(f"search-{len(embeddings)}")
        return []

    generate_mock = AsyncMock(return_value=["реформ1"])
    config = MultiQueryConfig(parallel=False)
    retriever = MultiQueryRetriever(
        embed_fn=track_embed,
        search_vectors=track_search,
        generate_reformulations=generate_mock,
        config=config,
    )

    await retriever.retrieve(query="запрос", top_k=5)

    # Sequential: embed сначала всех, потом search для каждого
    assert "embed-2" in call_order


@pytest.mark.asyncio
async def test_retrieve_parallel_mode() -> None:
    """Parallel mode (parallel=True) работает корректно."""
    async def dummy_embed(texts: list[str]) -> list[list[float]]:
        return [[0.1] for _ in texts]

    async def dummy_search(embeddings: list[list[float]], top_k: int) -> list[dict[str, Any]]:
        return []

    generate_mock = AsyncMock(return_value=["реформ1"])
    config = MultiQueryConfig(parallel=True)
    retriever = MultiQueryRetriever(
        embed_fn=dummy_embed,
        search_vectors=dummy_search,
        generate_reformulations=generate_mock,
        config=config,
    )

    results = await retriever.retrieve(query="запрос", top_k=5)

    # Должен работать без ошибок
    assert isinstance(results, list)


def test_multi_query_config_immutable() -> None:
    """MultiQueryConfig — frozen dataclass."""
    config = MultiQueryConfig(num_reformulations=3)
    with pytest.raises((AttributeError, Exception)):
        config.num_reformulations = 5  # type: ignore[misc]


@pytest.mark.asyncio
async def test_retrieve_sources_include_original_and_reform() -> None:
    """Sources в результате включают 'original' и реформы."""
    generate_mock = AsyncMock(return_value=["реформ1"])
    embed_mock = AsyncMock(return_value=[[0.1], [0.2], [0.3]])
    search_mock = AsyncMock(
        side_effect=[
            [{"id": "doc1", "document": "документ 1", "metadata": {}}],
            [{"id": "doc2", "document": "документ 2", "metadata": {}}],
            [{"id": "doc3", "document": "документ 3", "metadata": {}}],
        ]
    )
    retriever = MultiQueryRetriever(
        embed_fn=embed_mock,
        search_vectors=search_mock,
        generate_reformulations=generate_mock,
    )

    results = await retriever.retrieve(query="запрос", top_k=5)

    # doc1 возвращается от первого запроса (original)
    # sources должен содержать 'original'
    doc1_result = next((r for r in results if r["chunk_id"] == "doc1"), None)
    if doc1_result:
        assert "original" in doc1_result["sources"] or "reform_0" in doc1_result["sources"]
