"""Unit tests for RerankerProcessor."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.backend.dsl.engine.processors.ai.reranker import RerankerProcessor
from src.backend.dsl.engine.exchange import Exchange


class TestRerankerProcessor:
    """Tests for RerankerProcessor."""

    @pytest.mark.asyncio
    async def test_process_returns_empty_when_flag_disabled(self) -> None:
        processor = RerankerProcessor()
        exchange = MagicMock(spec=Exchange)
        exchange.in_message = MagicMock()
        exchange.in_message.body = {"question": "test"}
        exchange.properties = {}
        exchange.set_property = MagicMock()

        # S164 W1: patch the feature_flags module attribute directly
        # (lazy import + module side_effect unreliable across pytest versions).
        with patch(
            "src.backend.core.config.features.feature_flags.reranking_pipeline_enabled",
            False,
        ):
            await processor.process(exchange, MagicMock())

        exchange.set_property.assert_called_with("reranked_results", [])

    @pytest.mark.asyncio
    async def test_process_returns_empty_when_no_query(self) -> None:
        processor = RerankerProcessor()
        exchange = MagicMock(spec=Exchange)
        exchange.in_message = MagicMock()
        exchange.in_message.body = {}
        exchange.properties = {}
        exchange.set_property = MagicMock()

        with patch(
            "src.backend.core.config.features.feature_flags.reranking_pipeline_enabled",
            True,
        ):
            await processor.process(exchange, MagicMock())

        exchange.set_property.assert_called_with("reranked_results", [])

    @pytest.mark.asyncio
    async def test_process_returns_empty_when_no_candidates(self) -> None:
        processor = RerankerProcessor()
        exchange = MagicMock(spec=Exchange)
        exchange.in_message = MagicMock()
        exchange.in_message.body = {"question": "test"}
        exchange.properties = {"vector_results": []}
        exchange.set_property = MagicMock()

        with patch(
            "src.backend.core.config.features.feature_flags.reranking_pipeline_enabled",
            True,
        ):
            await processor.process(exchange, MagicMock())

        exchange.set_property.assert_called_with("reranked_results", [])

    def test_to_spec(self) -> None:
        processor = RerankerProcessor(top_k=10, latency_budget_ms=100.0)
        spec = processor.to_spec()
        assert spec is not None
        assert "rerank" in spec
        assert spec["rerank"]["top_k"] == 10
        assert spec["rerank"]["latency_budget_ms"] == 100.0
