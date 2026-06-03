"""Unit tests for LLMCallProcessor.

Covers: prompt from property, fallback to body, success with usage,
rate-limit failure, retry failure, to_spec.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from src.backend.dsl.engine.processors.ai.llmcall_processor import LLMCallProcessor


class _Message:
    def __init__(self, body: Any = None) -> None:
        self.body = body

    def set_body(self, value: Any) -> None:
        self.body = value


class _Exchange:
    def __init__(self, body: Any = None) -> None:
        self.properties: dict[str, Any] = {}
        self.in_message = _Message(body=body)

    def set_property(self, key: str, value: Any) -> None:
        self.properties[key] = value

    def fail(self, msg: str) -> None:
        self.properties["_error"] = msg


class _Context:
    pass


class TestLLMCallProcessor:
    """Tests for :class:`LLMCallProcessor`."""

    @pytest.mark.asyncio
    async def test_success_sets_properties(self) -> None:
        """Successful call sets llm.* properties and updates body."""
        proc = LLMCallProcessor(provider="openai", model="gpt-4")
        exchange = _Exchange(body="hi")

        mock_agent = AsyncMock()
        mock_agent.chat.return_value = {
            "content": "ok",
            "usage": {"total_tokens": 100},
            "model": "gpt-4-0613",
        }

        with patch(
            "src.backend.services.ai.ai_agent.get_ai_agent_service",
            return_value=mock_agent,
        ):
            await proc.process(exchange, _Context())

        assert exchange.properties.get("llm.provider") == "openai"
        assert exchange.properties.get("llm.model") == "gpt-4-0613"
        assert exchange.properties.get("llm.tokens_used") == 100
        assert exchange.properties.get("llm.cost_usd") == round(100 * 0.00002, 6)
        assert exchange.in_message.body == {"content": "ok", "usage": {"total_tokens": 100}, "model": "gpt-4-0613"}

    @pytest.mark.asyncio
    async def test_uses_prompt_property(self) -> None:
        """Uses prompt from properties if key exists."""
        proc = LLMCallProcessor(prompt_property="my_prompt")
        exchange = _Exchange(body="ignored")
        exchange.properties["my_prompt"] = "real prompt"

        mock_agent = AsyncMock()
        mock_agent.chat.return_value = "ok"

        with patch(
            "src.backend.services.ai.ai_agent.get_ai_agent_service",
            return_value=mock_agent,
        ):
            await proc.process(exchange, _Context())

        messages = mock_agent.chat.await_args.kwargs["messages"]
        assert messages[0]["content"] == "real prompt"

    @pytest.mark.asyncio
    async def test_rate_limit_failure(self) -> None:
        """Rate-limit RuntimeError fails exchange without retry."""
        proc = LLMCallProcessor()
        exchange = _Exchange(body="hi")

        mock_agent = AsyncMock()
        mock_agent.chat.side_effect = RuntimeError("rate limit 429")

        with patch(
            "src.backend.services.ai.ai_agent.get_ai_agent_service",
            return_value=mock_agent,
        ):
            await proc.process(exchange, _Context())

        assert "LLM rate limit" in exchange.properties.get("_error", "")

    @pytest.mark.asyncio
    async def test_retry_exhaustion(self) -> None:
        """After max_retries+1 attempts, transient errors fail exchange."""
        proc = LLMCallProcessor(max_retries=1, retry_delay=0.01)
        exchange = _Exchange(body="hi")

        mock_agent = AsyncMock()
        mock_agent.chat.side_effect = TimeoutError("timeout")

        with patch(
            "src.backend.services.ai.ai_agent.get_ai_agent_service",
            return_value=mock_agent,
        ):
            await proc.process(exchange, _Context())

        assert "LLM call failed after 2 attempts" in exchange.properties.get("_error", "")
        assert mock_agent.chat.await_count == 2

    @pytest.mark.asyncio
    async def test_missing_agent_service_fails(self) -> None:
        """ImportError on get_ai_agent_service fails exchange."""
        import builtins
        import sys

        proc = LLMCallProcessor()
        exchange = _Exchange(body="hi")

        real_import = builtins.__import__

        def fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
            if name == "src.backend.services.ai.ai_agent":
                raise ImportError("no module")
            return real_import(name, *args, **kwargs)

        with patch.dict("sys.modules", {}, clear=False):
            for k in list(sys.modules.keys()):
                if k == "src.backend.services.ai.ai_agent":
                    del sys.modules[k]
            with patch.object(builtins, "__import__", fake_import):
                await proc.process(exchange, _Context())

        assert "AI agent service unavailable" in exchange.properties.get("_error", "")

    def test_to_spec_with_values(self) -> None:
        """to_spec returns dict with provider/model when set."""
        proc = LLMCallProcessor(provider="p", model="m")
        spec = proc.to_spec()
        assert spec == {"call_llm": {"provider": "p", "model": "m"}}

    def test_to_spec_none_returns_empty_dict(self) -> None:
        """to_spec returns None when no provider/model set."""
        proc = LLMCallProcessor()
        assert proc.to_spec() == {"call_llm": {}}
