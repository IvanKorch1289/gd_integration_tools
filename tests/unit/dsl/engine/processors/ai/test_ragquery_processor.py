"""Unit tests for RagQueryProcessor."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.dsl.engine.processors.ai.ragquery_processor import RagQueryProcessor


class _Message:
    def __init__(self, body: Any = None) -> None:
        self.body = body


class _Exchange:
    def __init__(self, body: Any = None) -> None:
        self.in_message = _Message(body=body)
        self.properties: dict[str, Any] = {}

    def set_property(self, key: str, value: Any) -> None:
        self.properties[key] = value


class _Context:
    pass


class _FakeResult:
    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data

    def to_dict(self) -> dict[str, Any]:
        return dict(self._data)


class TestRagQueryProcessor:
    """Tests for :class:`RagQueryProcessor`."""

    def test_unknown_strategy_raises(self) -> None:
        with pytest.raises(ValueError, match="unknown rag strategy"):
            RagQueryProcessor(strategy="unknown")

    @pytest.mark.asyncio
    async def test_empty_query_sets_none(self) -> None:
        exchange = _Exchange(body={"question": ""})
        proc = RagQueryProcessor()
        await proc.process(exchange, _Context())
        assert exchange.properties["augment_result"] is None

    @pytest.mark.asyncio
    async def test_query_from_dict_body(self) -> None:
        exchange = _Exchange(body={"question": "q1"})
        proc = RagQueryProcessor(top_k=3, namespace="ns")

        with patch("src.backend.services.ai.rag_service.get_rag_service") as mock_get:
            mock_rag = AsyncMock()
            mock_rag.augment = AsyncMock(return_value=_FakeResult({"docs": []}))
            mock_get.return_value = mock_rag

            await proc.process(exchange, _Context())

        mock_rag.augment.assert_awaited_once_with(
            query="q1",
            system_prompt="",
            top_k=3,
            namespace="ns",
            max_staleness_hours=None,
        )
        assert exchange.properties["augment_result"]["strategy"] == "dense"
        assert exchange.properties["rag_strategy"] == "dense"

    @pytest.mark.asyncio
    async def test_query_from_string_body(self) -> None:
        exchange = _Exchange(body="plain query")
        proc = RagQueryProcessor()

        with patch("src.backend.services.ai.rag_service.get_rag_service") as mock_get:
            mock_rag = AsyncMock()
            mock_rag.augment = AsyncMock(return_value=_FakeResult({"r": 1}))
            mock_get.return_value = mock_rag

            await proc.process(exchange, _Context())

        call = mock_rag.augment.call_args
        assert call.kwargs["query"] == "plain query"

    @pytest.mark.asyncio
    async def test_adaptive_with_feature_flag_on(self) -> None:
        exchange = _Exchange(body="q")
        proc = RagQueryProcessor(strategy="adaptive")

        with (
            patch("src.backend.services.ai.rag_service.get_rag_service") as mock_get,
            patch("src.backend.core.config.features.feature_flags") as mock_flags,
        ):
            mock_flags.adaptive_rag_strategy = True

            mock_selector = AsyncMock()
            decision = MagicMock()
            decision.strategy = "hyde"
            decision.elapsed_ms = 12
            mock_selector.select = AsyncMock(return_value=decision)

            with patch(
                "src.backend.services.ai.rag.strategy_selector.AdaptiveStrategySelector",
                return_value=mock_selector,
            ):
                mock_rag = AsyncMock()
                mock_rag.augment = AsyncMock(return_value=_FakeResult({"r": 1}))
                mock_get.return_value = mock_rag

                await proc.process(exchange, _Context())

        assert exchange.properties["rag_strategy"] == "hyde"
        assert exchange.properties["rag_strategy_overhead_ms"] == 12

    @pytest.mark.asyncio
    async def test_adaptive_with_feature_flag_off(self) -> None:
        exchange = _Exchange(body="q")
        proc = RagQueryProcessor(strategy="adaptive")

        with (
            patch("src.backend.services.ai.rag_service.get_rag_service") as mock_get,
            patch("src.backend.core.config.features.feature_flags") as mock_flags,
        ):
            mock_flags.adaptive_rag_strategy = False
            mock_rag = AsyncMock()
            mock_rag.augment = AsyncMock(return_value=_FakeResult({"r": 1}))
            mock_get.return_value = mock_rag

            await proc.process(exchange, _Context())

        assert exchange.properties["rag_strategy"] == "dense"

    def test_to_spec_defaults(self) -> None:
        proc = RagQueryProcessor()
        assert proc.to_spec() == {"rag_query": {}}

    def test_to_spec_custom(self) -> None:
        proc = RagQueryProcessor(
            query_field="q",
            system_prompt="sys",
            top_k=10,
            namespace="n",
            strategy="hybrid",
            max_staleness_hours=1.0,
            output_property="out",
        )
        assert proc.to_spec() == {
            "rag_query": {
                "query_field": "q",
                "top_k": 10,
                "namespace": "n",
                "strategy": "hybrid",
                "max_staleness_hours": 1.0,
                "system_prompt": "sys",
                "output_property": "out",
            }
        }
