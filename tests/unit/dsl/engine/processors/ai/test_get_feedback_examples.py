"""Unit tests for GetFeedbackExamplesProcessor."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.backend.dsl.engine.processors.ai.getfeedbackexamples_processor import GetFeedbackExamplesProcessor
from src.backend.dsl.engine.exchange import Exchange


class TestGetFeedbackExamplesProcessor:
    """Tests for GetFeedbackExamplesProcessor."""

    @pytest.mark.asyncio
    async def test_process_returns_empty_when_no_query(self) -> None:
        processor = GetFeedbackExamplesProcessor()
        exchange = MagicMock(spec=Exchange)
        exchange.in_message = MagicMock()
        exchange.in_message.body = {}
        exchange.set_property = MagicMock()

        await processor.process(exchange, MagicMock())

        exchange.set_property.assert_called()

    @pytest.mark.asyncio
    async def test_process_returns_empty_when_no_examples(self) -> None:
        processor = GetFeedbackExamplesProcessor()
        exchange = MagicMock(spec=Exchange)
        exchange.in_message = MagicMock()
        exchange.in_message.body = {"question": "test"}
        exchange.set_property = MagicMock()

        with patch.object(processor, "_fetch_examples", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = []
            await processor.process(exchange, MagicMock())

        exchange.set_property.assert_called()

    def test_to_spec(self) -> None:
        processor = GetFeedbackExamplesProcessor(top_k=3)
        spec = processor.to_spec()
        assert spec is not None
        assert "get_feedback_examples" in spec
        assert spec["get_feedback_examples"]["top_k"] == 3
