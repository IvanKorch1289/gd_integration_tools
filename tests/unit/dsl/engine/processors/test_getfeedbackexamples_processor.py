"""Unit tests for GetFeedbackExamplesProcessor.

Covers: empty query, positive/negative split, property path, body path.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from src.backend.dsl.engine.processors.ai.getfeedbackexamples_processor import (
    GetFeedbackExamplesProcessor,
)


class _Message:
    def __init__(self, body: Any = None) -> None:
        self.body = body


class _Exchange:
    def __init__(self, properties: dict[str, Any] | None = None) -> None:
        self.properties = properties or {}
        self.in_message = _Message()

    def set_property(self, key: str, value: Any) -> None:
        self.properties[key] = value


class _Context:
    pass


class TestGetFeedbackExamplesProcessor:
    """Tests for :class:`GetFeedbackExamplesProcessor`."""

    @pytest.mark.asyncio
    async def test_empty_query_returns_empty_lists(self) -> None:
        """When query is empty/None, returns empty positive/negative lists."""
        proc = GetFeedbackExamplesProcessor(query_from="body.query")
        exchange = _Exchange()
        exchange.in_message.body = {"query": ""}
        await proc.process(exchange, _Context())
        result = exchange.properties["feedback_examples"]
        assert result == {"positive": [], "negative": []}

    @pytest.mark.asyncio
    async def test_positive_and_negative_split(self) -> None:
        """Splits RAG results into positive and negative examples."""
        proc = GetFeedbackExamplesProcessor(
            query_from="body.query",
            agent_id="agent1",
            positive_k=1,
            negative_k=1,
            min_similarity=0.5,
        )
        exchange = _Exchange()
        exchange.in_message.body = {"query": "hello"}

        mock_rag = AsyncMock()
        mock_rag.search.return_value = [
            {
                "document": "Q: q1\nA: a1",
                "metadata": {
                    "source": "ai_feedback",
                    "label": "positive",
                    "agent_id": "agent1",
                },
                "score": 0.9,
            },
            {
                "document": "Q: q2\nA: a2",
                "metadata": {
                    "source": "ai_feedback",
                    "label": "negative",
                    "agent_id": "agent1",
                },
                "score": 0.8,
            },
        ]

        with patch(
            "src.backend.services.ai.rag_service.get_rag_service", return_value=mock_rag
        ):
            await proc.process(exchange, _Context())

        result = exchange.properties["feedback_examples"]
        assert len(result["positive"]) == 1
        assert result["positive"][0] == {"query": "q1", "response": "a1"}
        assert len(result["negative"]) == 1
        assert result["negative"][0] == {"query": "q2", "response": "a2"}

    @pytest.mark.asyncio
    async def test_min_similarity_filters(self) -> None:
        """Results below min_similarity are dropped."""
        proc = GetFeedbackExamplesProcessor(
            query_from="body.query", positive_k=2, min_similarity=0.9
        )
        exchange = _Exchange()
        exchange.in_message.body = {"query": "x"}

        mock_rag = AsyncMock()
        mock_rag.search.return_value = [
            {
                "document": "Q: q1\nA: a1",
                "metadata": {"source": "ai_feedback", "label": "positive"},
                "score": 0.5,
            }
        ]

        with patch(
            "src.backend.services.ai.rag_service.get_rag_service", return_value=mock_rag
        ):
            await proc.process(exchange, _Context())

        result = exchange.properties["feedback_examples"]
        assert result["positive"] == []

    @pytest.mark.asyncio
    async def test_property_path(self) -> None:
        """query_from starting with 'property:' reads from exchange properties."""
        proc = GetFeedbackExamplesProcessor(query_from="property:my_query")
        exchange = _Exchange()
        exchange.properties["my_query"] = "from_prop"

        mock_rag = AsyncMock()
        mock_rag.search.return_value = []

        with patch(
            "src.backend.services.ai.rag_service.get_rag_service", return_value=mock_rag
        ):
            await proc.process(exchange, _Context())

        assert mock_rag.search.await_count == 2
        mock_rag.search.assert_any_await(
            query="from_prop", top_k=6, namespace="ai_feedback"
        )

    @pytest.mark.asyncio
    async def test_rag_unavailable_returns_empty(self) -> None:
        """If get_rag_service raises, returns empty lists silently."""
        proc = GetFeedbackExamplesProcessor(query_from="body.query")
        exchange = _Exchange()
        exchange.in_message.body = {"query": "q"}

        with patch(
            "src.backend.services.ai.rag_service.get_rag_service",
            side_effect=RuntimeError("down"),
        ):
            await proc.process(exchange, _Context())

        result = exchange.properties["feedback_examples"]
        assert result == {"positive": [], "negative": []}

    def test_parse_example_qa(self) -> None:
        """_parse_example extracts Q: and A: parts."""
        parsed = GetFeedbackExamplesProcessor._parse_example("Q: what?\nA: yes")
        assert parsed == {"query": "what?", "response": "yes"}

    def test_parse_example_no_q(self) -> None:
        """_parse_example without Q: prefix puts everything in response."""
        parsed = GetFeedbackExamplesProcessor._parse_example("just text")
        assert parsed == {"query": "", "response": "just text"}
