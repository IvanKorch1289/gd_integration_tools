"""Unit-тесты для :class:`AgentRunProcessor` (S27 W1)."""

from __future__ import annotations

from typing import Any

import pytest

from src.backend.core.ai.gateway import AIRequest, AIResponse
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange, Message
from src.backend.dsl.engine.processors.agent_dsl.agent_run import AgentRunProcessor


class _FakeAIGateway:
    """Минимальный fake :class:`AIGateway` для unit-тестов."""

    def __init__(self, response: AIResponse) -> None:
        self.response = response
        self.calls: list[AIRequest] = []

    async def invoke(self, request: AIRequest) -> AIResponse:
        self.calls.append(request)
        return self.response


@pytest.fixture
def fake_response() -> AIResponse:
    return AIResponse(
        content="approved",
        structured={"verdict": "approve", "score": 0.85},
        tokens_prompt=10,
        tokens_completion=5,
        cost_usd=0.001,
        model_used="gpt-4o",
        pii_detected=False,
        guardrails_verdict={"input": "safe", "output": "safe"},
    )


@pytest.fixture
def exchange() -> Exchange[Any]:
    ex: Exchange[Any] = Exchange(in_message=Message(body={"customer_id": 42}))
    ex.meta.tenant_id = "acme"
    ex.meta.correlation_id = "req-abc-123"
    return ex


@pytest.fixture
def context() -> ExecutionContext:
    return ExecutionContext()


def test_init_validates_workflow_id() -> None:
    with pytest.raises(ValueError, match="workflow_id обязателен"):
        AgentRunProcessor(workflow_id="", prompt_inline="x")


def test_init_validates_prompt_required() -> None:
    with pytest.raises(ValueError, match="prompt_ref или prompt_inline"):
        AgentRunProcessor(workflow_id="credit_check")


def test_init_accepts_prompt_ref_or_inline() -> None:
    p1 = AgentRunProcessor(workflow_id="x", prompt_ref="ref")
    p2 = AgentRunProcessor(workflow_id="x", prompt_inline="inline")
    assert p1.prompt_ref == "ref"
    assert p2.prompt_inline == "inline"


def test_name_default_includes_workflow_id() -> None:
    proc = AgentRunProcessor(workflow_id="credit_check", prompt_inline="x")
    assert proc.name == "agent_run:credit_check"


def test_capability_scope_returns_workflow_id() -> None:
    proc = AgentRunProcessor(workflow_id="credit_check", prompt_inline="x")
    ex: Exchange[Any] = Exchange()
    assert proc._capability_scope(ex) == "credit_check"


@pytest.mark.asyncio
async def test_feature_flag_off_is_pass_through(
    monkeypatch: pytest.MonkeyPatch, exchange: Exchange[Any], context: ExecutionContext
) -> None:
    """При выключенном feature_flag — processor — silent no-op."""
    from src.backend.core.config.features import feature_flags

    monkeypatch.setattr(feature_flags, "ai_agent_dsl_enabled", False)

    proc = AgentRunProcessor(workflow_id="credit_check", prompt_inline="x")
    await proc.process(exchange, context)
    assert exchange.get_property("agent_result") is None
    assert exchange.error is None


@pytest.mark.asyncio
async def test_happy_path_writes_agent_result(
    monkeypatch: pytest.MonkeyPatch,
    exchange: Exchange[Any],
    context: ExecutionContext,
    fake_response: AIResponse,
) -> None:
    from src.backend.core.config.features import feature_flags

    monkeypatch.setattr(feature_flags, "ai_agent_dsl_enabled", True)
    gw = _FakeAIGateway(fake_response)
    monkeypatch.setattr(AgentRunProcessor, "_resolve_gateway", staticmethod(lambda: gw))

    proc = AgentRunProcessor(workflow_id="credit_check", prompt_inline="check it")
    await proc.process(exchange, context)

    result = exchange.get_property("agent_result")
    assert result is not None
    assert result["content"] == "approved"
    assert result["model_used"] == "gpt-4o"
    assert result["tokens_prompt"] == 10
    assert result["tokens_completion"] == 5
    assert result["structured"] == {"verdict": "approve", "score": 0.85}

    assert len(gw.calls) == 1
    request = gw.calls[0]
    assert request.workflow_id == "credit_check"
    assert request.tenant_id == "acme"
    assert request.correlation_id == "req-abc-123"
    assert request.prompt_inline == "check it"
    assert request.context == {"customer_id": 42}


@pytest.mark.asyncio
async def test_missing_gateway_sets_error(
    monkeypatch: pytest.MonkeyPatch, exchange: Exchange[Any], context: ExecutionContext
) -> None:
    from src.backend.core.config.features import feature_flags

    monkeypatch.setattr(feature_flags, "ai_agent_dsl_enabled", True)
    monkeypatch.setattr(
        AgentRunProcessor, "_resolve_gateway", staticmethod(lambda: None)
    )

    proc = AgentRunProcessor(workflow_id="credit_check", prompt_inline="x")
    await proc.process(exchange, context)

    assert exchange.error is not None
    assert "AIGateway не найден" in exchange.error
    assert exchange.stopped


@pytest.mark.asyncio
async def test_extract_context_body_path(
    monkeypatch: pytest.MonkeyPatch,
    context: ExecutionContext,
    fake_response: AIResponse,
) -> None:
    """``context_property="body.subkey"`` извлекает nested dict."""
    from src.backend.core.config.features import feature_flags

    monkeypatch.setattr(feature_flags, "ai_agent_dsl_enabled", True)
    gw = _FakeAIGateway(fake_response)
    monkeypatch.setattr(AgentRunProcessor, "_resolve_gateway", staticmethod(lambda: gw))

    ex: Exchange[Any] = Exchange(in_message=Message(body={"context": {"key": "value"}}))
    proc = AgentRunProcessor(
        workflow_id="x", prompt_inline="x", context_property="body.context"
    )
    await proc.process(ex, context)
    assert gw.calls[0].context == {"key": "value"}


@pytest.mark.asyncio
async def test_extract_context_property_path(
    monkeypatch: pytest.MonkeyPatch,
    context: ExecutionContext,
    fake_response: AIResponse,
) -> None:
    """``context_property="property:my_prop"`` извлекает из properties."""
    from src.backend.core.config.features import feature_flags

    monkeypatch.setattr(feature_flags, "ai_agent_dsl_enabled", True)
    gw = _FakeAIGateway(fake_response)
    monkeypatch.setattr(AgentRunProcessor, "_resolve_gateway", staticmethod(lambda: gw))

    ex: Exchange[Any] = Exchange()
    ex.set_property("my_prop", {"alpha": 1})
    proc = AgentRunProcessor(
        workflow_id="x", prompt_inline="x", context_property="property:my_prop"
    )
    await proc.process(ex, context)
    assert gw.calls[0].context == {"alpha": 1}


def test_to_spec_round_trip_minimal() -> None:
    proc = AgentRunProcessor(workflow_id="credit_check", prompt_inline="x")
    spec = proc.to_spec()
    assert spec == {"agent_run": {"workflow_id": "credit_check", "prompt_inline": "x"}}


def test_to_spec_round_trip_full() -> None:
    proc = AgentRunProcessor(
        workflow_id="credit_check",
        prompt_ref="credit_check.production",
        policy_ref="credit_check_strict",
        context_property="body.ctx",
        result_property="my_result",
    )
    spec = proc.to_spec()
    assert spec == {
        "agent_run": {
            "workflow_id": "credit_check",
            "prompt_ref": "credit_check.production",
            "policy_ref": "credit_check_strict",
            "context_property": "body.ctx",
            "result_property": "my_result",
        }
    }
