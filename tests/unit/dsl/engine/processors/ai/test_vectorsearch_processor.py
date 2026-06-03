"""Unit tests for VectorSearchProcessor."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from src.backend.dsl.engine.processors.ai.vectorsearch_processor import (
    VectorSearchProcessor,
)


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


class TestVectorSearchProcessor:
    """Tests for :class:`VectorSearchProcessor`."""

    @pytest.mark.asyncio
    async def test_dict_body_with_query_field(self) -> None:
        exchange = _Exchange(body={"question": "q1"})
        proc = VectorSearchProcessor(top_k=3, namespace="ns")

        with patch("src.backend.services.ai.rag_service.get_rag_service") as mock_get:
            mock_rag = AsyncMock()
            mock_rag.search = AsyncMock(return_value=[{"id": 1}])
            mock_get.return_value = mock_rag

            await proc.process(exchange, _Context())

        mock_rag.search.assert_awaited_once_with(query="q1", top_k=3, namespace="ns")
        assert exchange.properties["vector_results"] == [{"id": 1}]

    @pytest.mark.asyncio
    async def test_string_body(self) -> None:
        exchange = _Exchange(body="plain query")
        proc = VectorSearchProcessor()

        with patch("src.backend.services.ai.rag_service.get_rag_service") as mock_get:
            mock_rag = AsyncMock()
            mock_rag.search = AsyncMock(return_value=[])
            mock_get.return_value = mock_rag

            await proc.process(exchange, _Context())

        call = mock_rag.search.call_args
        assert call.kwargs["query"] == "plain query"

    @pytest.mark.asyncio
    async def test_empty_query_returns_empty_list(self) -> None:
        exchange = _Exchange(body={"question": ""})
        proc = VectorSearchProcessor()

        with patch("src.backend.services.ai.rag_service.get_rag_service") as mock_get:
            await proc.process(exchange, _Context())

        mock_get.assert_not_called()
        assert exchange.properties["vector_results"] == []

    def test_to_spec_defaults(self) -> None:
        proc = VectorSearchProcessor()
        assert proc.to_spec() == {"rag_search": {}}

    def test_to_spec_custom(self) -> None:
        proc = VectorSearchProcessor(
            query_field="q", top_k=10, namespace="n", output_property="out"
        )
        assert proc.to_spec() == {
            "rag_search": {"query_field": "q", "top_k": 10, "namespace": "n"}
        }
