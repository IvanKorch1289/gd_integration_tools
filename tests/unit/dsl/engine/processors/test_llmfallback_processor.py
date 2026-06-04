"""Unit tests for LLMFallbackProcessor.

Covers: fallback chain, success on first, success on later, total failure.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from src.backend.dsl.engine.processors.ai.llmfallback_processor import (
    LLMFallbackProcessor,
)


class _Message:
    def __init__(self, body: Any = None) -> None:
        self.body = body

    def set_body(self, value: Any) -> None:
        self.body = value


class _Exchange:
    def __init__(self, properties: dict[str, Any] | None = None) -> None:
        self.properties = properties or {}
        self.in_message = _Message()
        self.out_message: _Message | None = None
        self._error: str | None = None

    def set_property(self, key: str, value: Any) -> None:
        self.properties[key] = value

    def fail(self, msg: str) -> None:
        self._error = msg


class _Context:
    pass


class TestLLMFallbackProcessor:
    """Tests for :class:`LLMFallbackProcessor`."""

    @pytest.fixture
    def exchange(self) -> _Exchange:
        return _Exchange()

    @pytest.mark.asyncio
    async def test_first_provider_succeeds(self, exchange: _Exchange) -> None:
        """Stops after first successful provider."""
        exchange.in_message.body = "hello"
        proc = LLMFallbackProcessor(providers=["p1", "p2"])

        mock_agent = AsyncMock()
        mock_agent.chat.return_value = {"content": "ok"}

        with patch(
            "src.backend.services.ai.ai_agent.get_ai_agent_service",
            return_value=mock_agent,
        ):
            await proc.process(exchange, _Context())

        assert exchange.in_message.body == {"content": "ok"}
        assert exchange.properties["llm_provider_used"] == "p1"
        assert exchange._error is None
        mock_agent.chat.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_second_provider_succeeds(self, exchange: _Exchange) -> None:
        """Falls back to second provider when first fails."""
        exchange.in_message.body = "hello"
        proc = LLMFallbackProcessor(providers=["p1", "p2"])

        mock_agent = AsyncMock()
        mock_agent.chat.side_effect = [RuntimeError("down"), {"content": "ok2"}]

        with patch(
            "src.backend.services.ai.ai_agent.get_ai_agent_service",
            return_value=mock_agent,
        ):
            await proc.process(exchange, _Context())

        assert exchange.in_message.body == {"content": "ok2"}
        assert exchange.properties["llm_provider_used"] == "p2"
        assert exchange._error is None
        assert mock_agent.chat.await_count == 2

    @pytest.mark.asyncio
    async def test_all_providers_fail(self, exchange: _Exchange) -> None:
        """Fails exchange when all providers fail."""
        exchange.in_message.body = "hello"
        proc = LLMFallbackProcessor(providers=["p1"])

        mock_agent = AsyncMock()
        mock_agent.chat.side_effect = RuntimeError("down")

        with patch(
            "src.backend.services.ai.ai_agent.get_ai_agent_service",
            return_value=mock_agent,
        ):
            await proc.process(exchange, _Context())

        assert exchange._error is not None
        assert "All LLM providers failed" in exchange._error

    @pytest.mark.asyncio
    async def test_uses_prompt_property(self, exchange: _Exchange) -> None:
        """Uses prompt from properties if present."""
        exchange.in_message.body = "ignored"
        exchange.properties["_composed_prompt"] = "real prompt"
        proc = LLMFallbackProcessor(providers=["p1"])

        mock_agent = AsyncMock()
        mock_agent.chat.return_value = "ok"

        with patch(
            "src.backend.services.ai.ai_agent.get_ai_agent_service",
            return_value=mock_agent,
        ):
            await proc.process(exchange, _Context())

        call_kwargs = mock_agent.chat.await_args.kwargs
        messages = call_kwargs["messages"]
        assert messages[0]["content"] == "real prompt"
