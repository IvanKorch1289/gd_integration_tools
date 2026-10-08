"""Unit tests for LLMCallProcessor.

Covers: prompt from property, fallback to body, success with usage,
rate-limit failure, retry failure, to_spec, gateway-enforce path.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

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


def _mock_flags(enforce: bool = False) -> MagicMock:
    flags = MagicMock()
    flags.ai_gateway_enforce = enforce
    return flags


#: Target of the litellm-price probe. Tests patch it so the cost contract is
#: deterministic regardless of whether ``litellm`` (and its pricing data) is
#: installed in the running environment.
_LITELLM_PROBE = (
    "src.backend.dsl.engine.processors.ai.llmcall_processor._try_litellm_cost"
)


class TestCostComputation:
    """Cost contract: litellm pricing wins, local table is the fallback."""

    def test_litellm_price_takes_priority(self) -> None:
        """When litellm knows the model, its price is used verbatim."""
        proc = LLMCallProcessor(model="gpt-4")
        with patch(_LITELLM_PROBE, return_value=0.123456) as probe:
            assert proc._compute_cost("gpt-4-0613", 50, 50) == 0.123456
        probe.assert_called_once_with("gpt-4-0613", 50, 50)

    @pytest.mark.parametrize(
        ("model", "rate"),
        [("gpt-4-0613", 0.00002), ("gpt-4", 0.00003), ("unknown", 0.00002)],
    )
    def test_fallback_table_when_litellm_unavailable(self, model: str, rate: float):
        """Without litellm, the local per-token table drives the estimate."""
        proc = LLMCallProcessor(model="gpt-4")
        with patch(_LITELLM_PROBE, return_value=None):
            assert proc._compute_cost(model, 50, 50) == rate * 100

    def test_litellm_errors_are_swallowed(self) -> None:
        """:func:`_try_litellm_cost` swallows litellm errors and returns None.

        The narrow-exception guard lives inside the probe itself, so it is
        exercised through a stub ``litellm`` module rather than by patching
        the probe (which would bypass the guard under test).
        """
        import sys
        import types

        from src.backend.dsl.engine.processors.ai.llmcall_processor import (
            _try_litellm_cost,
        )

        stub = types.ModuleType("litellm")

        def _boom(**kwargs: Any) -> float:
            raise ValueError("unknown model")

        stub.completion_cost = _boom  # type: ignore[attr-defined]

        with patch.dict(sys.modules, {"litellm": stub}):
            assert _try_litellm_cost("custom/model", 10, 10) is None

    def test_litellm_missing_returns_none(self) -> None:
        """Absent litellm degrades to ``None`` so the local table applies."""
        import sys
        import types

        from src.backend.dsl.engine.processors.ai.llmcall_processor import (
            _try_litellm_cost,
        )

        # A module without ``completion_cost`` makes the function-local
        # ``from litellm import completion_cost`` raise ImportError.
        stub = types.ModuleType("litellm")
        with patch.dict(sys.modules, {"litellm": stub}):
            assert _try_litellm_cost("gpt-4-0613", 10, 10) is None


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
            # S156 W8: include prompt_tokens and completion_tokens so
            # _compute_cost() can compute non-zero cost. Was only
            # total_tokens: 100, which split into prompt=0, completion=0.
            "usage": {
                "total_tokens": 100,
                "prompt_tokens": 50,
                "completion_tokens": 50,
            },
            "model": "gpt-4-0613",
        }

        with (
            patch(
                "src.backend.core.config.features.feature_flags",
                _mock_flags(enforce=False),
            ),
            patch(
                "src.backend.services.ai.ai_agent.get_ai_agent_service",
                return_value=mock_agent,
            ),
            patch(_LITELLM_PROBE, return_value=None),
        ):
            await proc.process(exchange, _Context())

        assert exchange.properties.get("llm.provider") == "openai"
        assert exchange.properties.get("llm.model") == "gpt-4-0613"
        assert exchange.properties.get("llm.tokens_used") == 100
        assert exchange.properties.get("llm.cost_usd") == round(100 * 0.00002, 6)
        assert exchange.in_message.body == {
            "content": "ok",
            "usage": {
                "total_tokens": 100,
                "prompt_tokens": 50,
                "completion_tokens": 50,
            },
            "model": "gpt-4-0613",
        }

    @pytest.mark.asyncio
    async def test_uses_prompt_property(self) -> None:
        """Uses prompt from properties if key exists."""
        proc = LLMCallProcessor(prompt_property="my_prompt")
        exchange = _Exchange(body="ignored")
        exchange.properties["my_prompt"] = "real prompt"

        mock_agent = AsyncMock()
        mock_agent.chat.return_value = "ok"

        with (
            patch(
                "src.backend.core.config.features.feature_flags",
                _mock_flags(enforce=False),
            ),
            patch(
                "src.backend.services.ai.ai_agent.get_ai_agent_service",
                return_value=mock_agent,
            ),
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

        with (
            patch(
                "src.backend.core.config.features.feature_flags",
                _mock_flags(enforce=False),
            ),
            patch(
                "src.backend.services.ai.ai_agent.get_ai_agent_service",
                return_value=mock_agent,
            ),
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

        with (
            patch(
                "src.backend.core.config.features.feature_flags",
                _mock_flags(enforce=False),
            ),
            patch(
                "src.backend.services.ai.ai_agent.get_ai_agent_service",
                return_value=mock_agent,
            ),
        ):
            await proc.process(exchange, _Context())

        assert "LLM call failed after 2 attempts" in exchange.properties.get(
            "_error", ""
        )
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

        with (
            patch(
                "src.backend.core.config.features.feature_flags",
                _mock_flags(enforce=False),
            ),
            patch.dict("sys.modules", {}, clear=False),
        ):
            for k in list(sys.modules.keys()):
                if k == "src.backend.services.ai.ai_agent":
                    del sys.modules[k]
            with patch.object(builtins, "__import__", fake_import):
                await proc.process(exchange, _Context())

        assert "AI agent service unavailable" in exchange.properties.get("_error", "")

    @pytest.mark.asyncio
    async def test_gateway_enforce_uses_aigateway(self) -> None:
        """When ai_gateway_enforce=True, call routes through AIGateway."""
        proc = LLMCallProcessor(provider="openai", model="gpt-4")
        exchange = _Exchange(body="hi")

        mock_response = MagicMock()
        mock_response.content = "ok"
        mock_response.tokens_prompt = 50
        mock_response.tokens_completion = 50
        mock_response.model_used = "gpt-4-0613"

        with (
            patch(
                "src.backend.core.config.features.feature_flags",
                _mock_flags(enforce=True),
            ),
            patch("src.backend.core.ai.gateway.AIGateway") as MockGW,
            patch(_LITELLM_PROBE, return_value=None),
        ):
            MockGW.return_value.invoke = AsyncMock(return_value=mock_response)
            await proc.process(exchange, _Context())

        assert exchange.properties.get("llm.provider") == "gateway"
        assert exchange.properties.get("llm.model") == "gpt-4-0613"
        assert exchange.properties.get("llm.tokens_used") == 100
        assert exchange.properties.get("llm.cost_usd") == round(100 * 0.00002, 6)
        assert exchange.in_message.body == {
            "content": "ok",
            "usage": {
                "total_tokens": 100,
                "prompt_tokens": 50,
                "completion_tokens": 50,
            },
            "model": "gpt-4-0613",
        }

    def test_to_spec_with_values(self) -> None:
        """to_spec returns dict with provider/model when set."""
        proc = LLMCallProcessor(provider="p", model="m")
        spec = proc.to_spec()
        assert spec == {"call_llm": {"provider": "p", "model": "m"}}

    def test_to_spec_none_returns_empty_dict(self) -> None:
        """to_spec returns None when no provider/model set."""
        proc = LLMCallProcessor()
        assert proc.to_spec() == {"call_llm": {}}
