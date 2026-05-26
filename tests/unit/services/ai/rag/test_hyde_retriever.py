"""Unit-тесты HyDERetriever (wave:s19/k4-w6-adaptive-rag-strategy-finale).

Проверяет:
1. retrieve() с валидным query возвращает HyDEResult.
2. retrieve() с пустым query возвращает пустой список.
3. generate_hypothetical вызывается с правильными параметрами.
4. embed_fn вызывается с гипотетическим документом.
5. Graceful fallback при генерации/embed/search failure.
6. HyDEConfig dataclass immutable.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from src.backend.services.ai.rag.hyde_retriever import (
    HyDEConfig,
    HyDEResult,
    HyDERetriever,
)


@pytest.mark.asyncio
async def test_retrieve_returns_hyde_results() -> None:
    """Успешный retrieve возвращает HyDEResult."""
    generate_mock = AsyncMock(
        return_value="Гипотетический ответ на вопрос о кредитной политике."
    )
    embed_mock = AsyncMock(return_value=[[0.1, 0.2, 0.3]])
    search_mock = AsyncMock(
        return_value=[
            {"id": "doc1", "document": "реальный документ", "metadata": {}},
        ]
    )
    retriever = HyDERetriever(
        embed_fn=embed_mock,
        search_vectors=search_mock,
        generate_hypothetical=generate_mock,
    )

    results = await retriever.retrieve(query="кредитная политика", top_k=3)

    assert len(results) == 1
    assert results[0]["chunk_id"] == "doc1"
    assert results[0]["document"] == "реальный документ"
    assert "hypothetical_document" in results[0]


@pytest.mark.asyncio
async def test_retrieve_empty_query_returns_empty() -> None:
    """Пустой query возвращает пустой список."""
    generate_mock = AsyncMock()
    embed_mock = AsyncMock()
    search_mock = AsyncMock()
    retriever = HyDERetriever(
        embed_fn=embed_mock,
        search_vectors=search_mock,
        generate_hypothetical=generate_mock,
    )

    results = await retriever.retrieve(query="   ", top_k=5)

    assert results == []
    generate_mock.assert_not_called()
    embed_mock.assert_not_called()


@pytest.mark.asyncio
async def test_generate_hypothetical_called_with_correct_args() -> None:
    """Generate вызывается с template и параметрами из config."""
    captured_args: dict[str, Any] = {}

    async def capture_generate(prompt: str, max_tokens: int, temperature: float) -> str:
        captured_args["prompt"] = prompt
        captured_args["max_tokens"] = max_tokens
        captured_args["temperature"] = temperature
        return "гипотетический документ"

    embed_mock = AsyncMock(return_value=[[0.1]])
    search_mock = AsyncMock(return_value=[])
    config = HyDEConfig(max_tokens=128, temperature=0.2)
    retriever = HyDERetriever(
        embed_fn=embed_mock,
        search_vectors=search_mock,
        generate_hypothetical=capture_generate,
        config=config,
    )

    await retriever.retrieve(query="тестовый запрос", top_k=5)

    assert "тестовый запрос" in captured_args["prompt"]
    assert captured_args["max_tokens"] == 128
    assert captured_args["temperature"] == 0.2


@pytest.mark.asyncio
async def test_retrieve_embed_failure_returns_empty() -> None:
    """Embed failure → empty list."""
    generate_mock = AsyncMock(return_value="гипотетический документ")
    embed_mock = AsyncMock(side_effect=RuntimeError("embedding down"))
    search_mock = AsyncMock()
    retriever = HyDERetriever(
        embed_fn=embed_mock,
        search_vectors=search_mock,
        generate_hypothetical=generate_mock,
    )

    results = await retriever.retrieve(query="запрос", top_k=5)

    assert results == []
    search_mock.assert_not_called()


@pytest.mark.asyncio
async def test_retrieve_search_failure_returns_empty() -> None:
    """Search failure → empty list."""
    generate_mock = AsyncMock(return_value="гипотетический документ")
    embed_mock = AsyncMock(return_value=[[0.1]])
    search_mock = AsyncMock(side_effect=RuntimeError("vector store down"))
    retriever = HyDERetriever(
        embed_fn=embed_mock,
        search_vectors=search_mock,
        generate_hypothetical=generate_mock,
    )

    results = await retriever.retrieve(query="запрос", top_k=5)

    assert results == []


@pytest.mark.asyncio
async def test_retrieve_generate_failure_returns_empty() -> None:
    """Generate failure → empty list."""
    generate_mock = AsyncMock(side_effect=RuntimeError("LLM down"))
    embed_mock = AsyncMock()
    search_mock = AsyncMock()
    retriever = HyDERetriever(
        embed_fn=embed_mock,
        search_vectors=search_mock,
        generate_hypothetical=generate_mock,
    )

    results = await retriever.retrieve(query="запрос", top_k=5)

    assert results == []
    embed_mock.assert_not_called()


@pytest.mark.asyncio
async def test_retrieve_empty_hypothetical_returns_empty() -> None:
    """Empty hypothetical → empty list."""
    generate_mock = AsyncMock(return_value="   ")
    embed_mock = AsyncMock()
    search_mock = AsyncMock()
    retriever = HyDERetriever(
        embed_fn=embed_mock,
        search_vectors=search_mock,
        generate_hypothetical=generate_mock,
    )

    results = await retriever.retrieve(query="запрос", top_k=5)

    assert results == []
    embed_mock.assert_not_called()


@pytest.mark.asyncio
async def test_retrieve_hypothetical_included_when_configured() -> None:
    """При include_hypothetical_in_result=True, hypothetical_document не пустой."""
    generate_mock = AsyncMock(return_value="ответ на вопрос")
    embed_mock = AsyncMock(return_value=[[0.1]])
    search_mock = AsyncMock(
        return_value=[{"id": "doc1", "document": "документ", "metadata": {}}]
    )
    config = HyDEConfig(include_hypothetical_in_result=True)
    retriever = HyDERetriever(
        embed_fn=embed_mock,
        search_vectors=search_mock,
        generate_hypothetical=generate_mock,
        config=config,
    )

    results = await retriever.retrieve(query="запрос", top_k=5)

    assert results[0]["hypothetical_document"] == "ответ на вопрос"


@pytest.mark.asyncio
async def test_retrieve_hypothetical_excluded_when_not_configured() -> None:
    """По умолчанию hypothetical_document пустой."""
    generate_mock = AsyncMock(return_value="ответ на вопрос")
    embed_mock = AsyncMock(return_value=[[0.1]])
    search_mock = AsyncMock(
        return_value=[{"id": "doc1", "document": "документ", "metadata": {}}]
    )
    retriever = HyDERetriever(
        embed_fn=embed_mock,
        search_vectors=search_mock,
        generate_hypothetical=generate_mock,
    )

    results = await retriever.retrieve(query="запрос", top_k=5)

    assert results[0]["hypothetical_document"] == ""


def test_hyde_config_immutable() -> None:
    """HyDEConfig — frozen dataclass."""
    config = HyDEConfig(max_tokens=128)
    with pytest.raises((AttributeError, Exception)):
        config.max_tokens = 256  # type: ignore[misc]


@pytest.mark.asyncio
async def test_retrieve_uses_default_config() -> None:
    """Без config используется HyDEConfig defaults."""
    generate_mock = AsyncMock(return_value="документ")
    embed_mock = AsyncMock(return_value=[[0.1]])
    search_mock = AsyncMock(return_value=[])
    retriever = HyDERetriever(
        embed_fn=embed_mock,
        search_vectors=search_mock,
        generate_hypothetical=generate_mock,
    )
    #Defaults: max_tokens=256, temperature=0.1
    await retriever.retrieve(query="запрос", top_k=5)
    # Проверяем что generate был вызван с defaults
    generate_mock.assert_called_once()
    call_args = generate_mock.call_args
    assert call_args.kwargs["max_tokens"] == 256
    assert call_args.kwargs["temperature"] == 0.1
