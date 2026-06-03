"""Unit tests for SemanticRouterProcessor."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from src.backend.dsl.engine.processors.ai.semanticrouter_processor import (
    SemanticRouterProcessor,
)


class _Message:
    def __init__(self, body: Any = None) -> None:
        self.body = body
        self.headers: dict[str, Any] = {}


class _Exchange:
    def __init__(self, body: Any = None) -> None:
        self.in_message = _Message(body=body)
        self.out_message: _Message | None = None
        self.properties: dict[str, Any] = {}

    def set_property(self, key: str, value: Any) -> None:
        self.properties[key] = value

    def set_out(self, body: Any = None, headers: dict[str, Any] | None = None) -> None:
        self.out_message = _Message(body=body)
        if headers:
            self.out_message.headers = headers

    def fail(self, msg: str) -> None:
        self.properties["_error"] = msg


class _Context:
    pass


class TestSemanticRouterProcessor:
    """Tests for :class:`SemanticRouterProcessor`."""

    @pytest.mark.asyncio
    async def test_empty_query_routes_to_default(self) -> None:
        exchange = _Exchange(body={"question": ""})
        proc = SemanticRouterProcessor(
            intents={"a": "route.a"}, default_route="route.default"
        )

        with patch(
            "src.backend.dsl.engine.processors.base.SubPipelineExecutor.execute_route",
            new=AsyncMock(return_value=("result", None)),
        ):
            await proc.process(exchange, _Context())

        assert exchange.out_message is not None
        assert exchange.out_message.body == "result"

    @pytest.mark.asyncio
    async def test_empty_query_fails_without_default(self) -> None:
        exchange = _Exchange(body="")
        proc = SemanticRouterProcessor(intents={"a": "route.a"})
        await proc.process(exchange, _Context())
        assert "empty query and no default_route" in exchange.properties["_error"]

    @pytest.mark.asyncio
    async def test_routes_by_intent(self) -> None:
        exchange = _Exchange(body="billing question")
        proc = SemanticRouterProcessor(
            intents={"billing": "route.billing"},
            default_route="route.default",
            threshold=0.5,
        )

        with (
            patch("src.backend.services.ai.rag_service.get_rag_service") as mock_get,
            patch(
                "src.backend.dsl.engine.processors.base.SubPipelineExecutor.execute_route",
                new=AsyncMock(return_value=("billing-result", None)),
            ),
        ):
            mock_rag = AsyncMock()
            mock_rag.search = AsyncMock(
                return_value=[{"score": 0.9, "intent": "billing"}]
            )
            mock_get.return_value = mock_rag

            await proc.process(exchange, _Context())

        assert exchange.properties["semantic_route_intent"] == "billing"
        assert exchange.properties["semantic_route_score"] == 0.9
        assert exchange.out_message is not None
        assert exchange.out_message.body == "billing-result"

    @pytest.mark.asyncio
    async def test_falls_back_when_score_below_threshold(self) -> None:
        exchange = _Exchange(body="something")
        proc = SemanticRouterProcessor(
            intents={"a": "route.a"}, default_route="route.def", threshold=0.8
        )

        with (
            patch("src.backend.services.ai.rag_service.get_rag_service") as mock_get,
            patch(
                "src.backend.dsl.engine.processors.base.SubPipelineExecutor.execute_route",
                new=AsyncMock(return_value=("def-result", None)),
            ),
        ):
            mock_rag = AsyncMock()
            mock_rag.search = AsyncMock(return_value=[{"score": 0.3, "intent": "a"}])
            mock_get.return_value = mock_rag

            await proc.process(exchange, _Context())

        assert exchange.out_message is not None
        assert exchange.out_message.body == "def-result"

    @pytest.mark.asyncio
    async def test_rag_error_with_default_fallback(self) -> None:
        exchange = _Exchange(body="q")
        proc = SemanticRouterProcessor(
            intents={"a": "route.a"}, default_route="route.def"
        )

        with (
            patch("src.backend.services.ai.rag_service.get_rag_service") as mock_get,
            patch(
                "src.backend.dsl.engine.processors.base.SubPipelineExecutor.execute_route",
                new=AsyncMock(return_value=("fallback", None)),
            ),
        ):
            mock_rag = AsyncMock()
            mock_rag.search = AsyncMock(side_effect=ConnectionError("rag down"))
            mock_get.return_value = mock_rag

            await proc.process(exchange, _Context())

        assert exchange.properties.get("semantic_route_fallback") is not None
        assert exchange.out_message is not None
        assert exchange.out_message.body == "fallback"

    @pytest.mark.asyncio
    async def test_rag_error_without_default_fails(self) -> None:
        exchange = _Exchange(body="q")
        proc = SemanticRouterProcessor(intents={"a": "route.a"})

        with patch("src.backend.services.ai.rag_service.get_rag_service") as mock_get:
            mock_rag = AsyncMock()
            mock_rag.search = AsyncMock(side_effect=RuntimeError("fail"))
            mock_get.return_value = mock_rag

            await proc.process(exchange, _Context())

        assert "RAG search failed" in exchange.properties["_error"]

    @pytest.mark.asyncio
    async def test_no_matching_intent_fails(self) -> None:
        exchange = _Exchange(body="q")
        proc = SemanticRouterProcessor(intents={"a": "route.a"})

        with patch("src.backend.services.ai.rag_service.get_rag_service") as mock_get:
            mock_rag = AsyncMock()
            mock_rag.search = AsyncMock(return_value=[])
            mock_get.return_value = mock_rag

            await proc.process(exchange, _Context())

        assert "no matching intent" in exchange.properties["_error"]

    @pytest.mark.asyncio
    async def test_route_execution_error_fails_exchange(self) -> None:
        exchange = _Exchange(body="q")
        proc = SemanticRouterProcessor(
            intents={"a": "route.a"}, default_route="route.def"
        )

        with (
            patch("src.backend.services.ai.rag_service.get_rag_service") as mock_get,
            patch(
                "src.backend.dsl.engine.processors.base.SubPipelineExecutor.execute_route",
                new=AsyncMock(return_value=(None, "exec error")),
            ),
        ):
            mock_rag = AsyncMock()
            mock_rag.search = AsyncMock(return_value=[])
            mock_get.return_value = mock_rag

            await proc.process(exchange, _Context())

        # No results -> no matching intent, so default_route tried, returned error
        assert "route.def failed" in exchange.properties["_error"]
