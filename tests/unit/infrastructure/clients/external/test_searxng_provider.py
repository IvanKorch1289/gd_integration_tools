"""Unit-тесты SearXNGProvider (PLAN #5: Search-DSL extension).

Smoke-coverage для нового free SearXNG search-провайдера в WebSearchService chain.
"""

# ruff: noqa: S101

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.infrastructure.clients.external.search_providers import (
    SearXNGProvider,
    WebSearchService,
)


@pytest.mark.asyncio
async def test_searxng_provider_search_returns_results() -> None:
    """SearXNGProvider возвращает результаты в стандартизированном формате."""
    provider = SearXNGProvider(base_url="http://searxng:8080")

    mock_response = MagicMock()
    mock_response.json.return_value = {
        "results": [
            {
                "title": "Test Title",
                "url": "https://example.com",
                "content": "Test snippet",
                "engine": "google",
            },
            {
                "title": "Title 2",
                "url": "https://example2.com",
                "content": "Snippet 2",
                "engine": "bing",
            },
        ]
    }
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.get = AsyncMock(return_value=mock_response)

    with patch("httpx.AsyncClient", return_value=mock_client):
        results = await provider.search("python testing")

    assert len(results) == 2
    assert results[0]["title"] == "Test Title"
    assert results[0]["url"] == "https://example.com"
    assert results[0]["engine"] == "google"


@pytest.mark.asyncio
async def test_searxng_provider_respects_max_results() -> None:
    """max_results обрезает количество возвращаемых элементов."""
    provider = SearXNGProvider(base_url="http://searxng:8080")

    mock_response = MagicMock()
    mock_response.json.return_value = {
        "results": [{"title": f"r{i}", "url": "", "content": ""} for i in range(20)]
    }
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.get = AsyncMock(return_value=mock_response)

    with patch("httpx.AsyncClient", return_value=mock_client):
        results = await provider.search("query", max_results=3)

    assert len(results) == 3


@pytest.mark.asyncio
async def test_searxng_provider_default_engines() -> None:
    """По умолчанию используются google,bing,duckduckgo."""
    provider = SearXNGProvider(base_url="http://searxng:8080")
    assert provider._engines == ["google", "bing", "duckduckgo"]


@pytest.mark.asyncio
async def test_searxng_provider_custom_engines() -> None:
    """Custom engines list передаётся в query params."""
    provider = SearXNGProvider(
        base_url="http://searxng:8080", engines=["wikipedia", "yahoo"]
    )
    assert provider._engines == ["wikipedia", "yahoo"]


@pytest.mark.asyncio
async def test_searxng_deep_research_falls_back_to_search() -> None:
    """deep_research возвращает обёртку над обычным search (SearXNG не поддерживает deep)."""
    provider = SearXNGProvider(base_url="http://searxng:8080")

    mock_response = MagicMock()
    mock_response.json.return_value = {
        "results": [{"title": "r", "url": "", "content": ""}]
    }
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.get = AsyncMock(return_value=mock_response)

    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await provider.deep_research("test query")

    assert result["query"] == "test query"
    assert result["provider"] == "searxng"
    assert len(result["results"]) == 1


@pytest.mark.asyncio
async def test_websearch_service_chain_includes_searxng_when_configured() -> None:
    """WebSearchService.add_provider() работает с SearXNGProvider."""
    service = WebSearchService()
    provider = SearXNGProvider(base_url="http://searxng:8080")
    service.add_provider(provider)

    assert any(p.name == "searxng" for p in service._providers)


def test_searxng_provider_name_constant() -> None:
    """Имя провайдера — 'searxng' (используется в provider routing)."""
    assert SearXNGProvider.name == "searxng"
    p = SearXNGProvider(base_url="http://x")
    assert p.name == "searxng"
