"""Unit tests for TokenBudgetProcessor."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from src.backend.dsl.engine.processors.ai.tokenbudget_processor import (
    TokenBudgetProcessor,
)


class _Message:
    def __init__(self, body: Any = None) -> None:
        self.body = body

    def set_body(self, value: Any) -> None:
        self.body = value


class _Exchange:
    def __init__(
        self, body: Any = None, properties: dict[str, Any] | None = None
    ) -> None:
        self.in_message = _Message(body=body)
        self.properties: dict[str, Any] = properties or {}

    def set_property(self, key: str, value: Any) -> None:
        self.properties[key] = value


class _Context:
    pass


class TestTokenBudgetProcessor:
    """Tests for :class:`TokenBudgetProcessor`."""

    @pytest.mark.asyncio
    async def test_truncates_when_over_limit(self) -> None:
        exchange = _Exchange(body="word " * 2000)
        proc = TokenBudgetProcessor(max_tokens=100)
        mock_encoder = MagicMock()
        mock_encoder.encode.return_value = list(range(2000))
        mock_encoder.decode.return_value = "word " * 100
        proc._encoder = mock_encoder

        await proc.process(exchange, _Context())
        assert "[truncated]" in exchange.in_message.body

    @pytest.mark.asyncio
    async def test_no_truncation_when_under_limit(self) -> None:
        exchange = _Exchange(body="short text")
        proc = TokenBudgetProcessor(max_tokens=100)
        mock_encoder = MagicMock()
        mock_encoder.encode.return_value = list(range(5))
        mock_encoder.decode.return_value = "short text"
        proc._encoder = mock_encoder

        await proc.process(exchange, _Context())
        assert "[truncated]" not in exchange.in_message.body
        assert exchange.in_message.body == "short text"

    @pytest.mark.asyncio
    async def test_fallback_char_truncation(self) -> None:
        exchange = _Exchange(body="x" * 5000)
        proc = TokenBudgetProcessor(max_tokens=100)
        proc._encoder = None

        await proc.process(exchange, _Context())
        assert len(exchange.in_message.body) <= 400 + len("\n...[truncated]")
        assert "[truncated]" in exchange.in_message.body

    @pytest.mark.asyncio
    async def test_truncates_source_property(self) -> None:
        exchange = _Exchange()
        exchange.set_property("long_text", "y " * 5000)
        proc = TokenBudgetProcessor(max_tokens=50, source_property="long_text")
        mock_encoder = MagicMock()
        mock_encoder.encode.return_value = list(range(5000))
        mock_encoder.decode.return_value = "y " * 50
        proc._encoder = mock_encoder

        await proc.process(exchange, _Context())
        assert "[truncated]" in exchange.properties["long_text"]

    @pytest.mark.asyncio
    async def test_ignores_non_string_body(self) -> None:
        exchange = _Exchange(body={"key": "val"})
        proc = TokenBudgetProcessor(max_tokens=100)
        await proc.process(exchange, _Context())
        assert exchange.in_message.body == {"key": "val"}

    @pytest.mark.asyncio
    async def test_ignores_non_string_property(self) -> None:
        exchange = _Exchange()
        exchange.set_property("data", {"key": "val"})
        proc = TokenBudgetProcessor(max_tokens=100, source_property="data")
        await proc.process(exchange, _Context())
        assert exchange.properties["data"] == {"key": "val"}
