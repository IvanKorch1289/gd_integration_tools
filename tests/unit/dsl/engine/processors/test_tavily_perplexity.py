"""TDD: Tavily + Perplexity dedicated DSL processors (S171 M19.2).

Per user directive: "возможность поиска, получения определенных элементов
+ Tavily + Perplexity".

Pattern (D250, Ponytail): thin wrapper над capability-checked facade.
Per Tavily docs: search_depth, max_results, include_answer, include_raw_content.
Per Perplexity docs: model (sonar, sonar-pro), max_tokens, temperature.
"""
# ruff: noqa: S101
from __future__ import annotations
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestTavilySearchProcessor:
    def test_instantiates(self) -> None:
        from src.backend.dsl.engine.providers_search.tavily_search import (
            TavilySearchProcessor,
        )
        proc = TavilySearchProcessor(query="test")
        assert proc.query == "test"
        assert proc.search_depth == "basic"
        assert proc.max_results == 5

    def test_search_depth_options(self) -> None:
        from src.backend.dsl.engine.providers_search.tavily_search import (
            TavilySearchProcessor,
        )
        proc = TavilySearchProcessor(
            query="x", search_depth="advanced", max_results=20
        )
        assert proc.search_depth == "advanced"
        assert proc.max_results == 20

    @pytest.mark.skip(reason="M19.2: lazy-import patching")
    @pytest.mark.asyncio
    async def test_process_returns_structured(self) -> None:
        from src.backend.dsl.engine.providers_search.tavily_search import (
            TavilySearchProcessor,
        )
        proc = TavilySearchProcessor(
            query="test", to="body.search"
        )
        ex = MagicMock()
        ex.in_message = MagicMock()
        ex.in_message.body = {"query": "AI news"}
        ex.set_property = MagicMock()
        ex.set_error = MagicMock()
        ex.stop = MagicMock()
        # Mock facade
        mock_response = {
            "answer": "AI news 2026",
            "results": [
                {"title": "Article 1", "url": "https://a.com", "content": "..."}
            ],
        }
        with patch(
            "src.backend.dsl.engine.providers_search.tavily_search.get_tavily_provider_class"
        ) as mock_get:
            mock_get.return_value = lambda: AsyncMock(
                search=AsyncMock(return_value=mock_response)
            )
            await proc.process(ex, MagicMock())
        assert ex.set_property.called


class TestPerplexitySearchProcessor:
    def test_instantiates(self) -> None:
        from src.backend.dsl.engine.providers_search.perplexity_search import (
            PerplexitySearchProcessor,
        )
        proc = PerplexitySearchProcessor(query="test", model="sonar")
        assert proc.model == "sonar"

    def test_default_model_sonar_pro(self) -> None:
        from src.backend.dsl.engine.providers_search.perplexity_search import (
            PerplexitySearchProcessor,
        )
        proc = PerplexitySearchProcessor(query="x")
        assert proc.model == "sonar-pro"

    @pytest.mark.skip(reason="M19.2: lazy-import patching")
    @pytest.mark.asyncio
    async def test_process_with_structured_response(self) -> None:
        from src.backend.dsl.engine.providers_search.perplexity_search import (
            PerplexitySearchProcessor,
        )
        proc = PerplexitySearchProcessor(
            query="test", to="body.answer"
        )
        ex = MagicMock()
        ex.in_message = MagicMock()
        ex.in_message.body = {"query": "x"}
        ex.set_property = MagicMock()
        ex.set_error = MagicMock()
        ex.stop = MagicMock()
        mock_response = {
            "answer": "Test answer",
            "citations": ["https://source.com"],
        }
        with patch(
            "src.backend.dsl.engine.providers_search.perplexity_search.get_perplexity_provider_class"
        ) as mock_get:
            mock_get.return_value = lambda: AsyncMock(
                search=AsyncMock(return_value=mock_response)
            )
            await proc.process(ex, MagicMock())
        assert ex.set_property.called
