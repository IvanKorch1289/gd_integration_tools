"""Unit-тесты для :class:`AgentParallelProcessor` (S27 W1)."""

from __future__ import annotations

from typing import Any

import pytest

from src.backend.core.ai.gateway import AIRequest, AIResponse
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange, Message
from src.backend.dsl.engine.processors.agent_dsl.agent_parallel import (
    AgentParallelProcessor,
)
from src.backend.dsl.engine.processors.agent_dsl.agent_run import AgentRunProcessor


class _FakeAIGateway:
    """Возвращает response по workflow_id из словаря."""

    def __init__(self, responses: dict[str, AIResponse]) -> None:
        self.responses = responses
        self.calls: list[AIRequest] = []

    async def invoke(self, request: AIRequest) -> AIResponse:
        self.calls.append(request)
        if request.workflow_id == "fail_me":
            raise RuntimeError("synthetic failure")
        return self.responses.get(
            request.workflow_id,
            AIResponse(content="default", model_used="m"),
        )


@pytest.fixture
def context() -> ExecutionContext:
    return ExecutionContext()


def test_init_validates_non_empty_agents() -> None:
    with pytest.raises(ValueError, match="не может быть пустым"):
        AgentParallelProcessor(agents=[])


def test_init_validates_key_required() -> None:
    with pytest.raises(ValueError, match="без 'key'"):
        AgentParallelProcessor(
            agents=[{"workflow_id": "x", "prompt_inline": "y"}]
        )


def test_init_validates_workflow_id_required() -> None:
    with pytest.raises(ValueError, match="без 'workflow_id'"):
        AgentParallelProcessor(agents=[{"key": "x", "prompt_inline": "y"}])


@pytest.mark.asyncio
async def test_fan_out_collects_results_by_key(
    monkeypatch: pytest.MonkeyPatch,
    context: ExecutionContext,
) -> None:
    from src.backend.core.config.features import feature_flags

    monkeypatch.setattr(feature_flags, "ai_agent_dsl_enabled", True)
    gw = _FakeAIGateway(
        {
            "scoring": AIResponse(content="80", model_used="m1"),
            "antifraud": AIResponse(content="low", model_used="m2"),
        }
    )
    monkeypatch.setattr(
        AgentRunProcessor, "_resolve_gateway", staticmethod(lambda: gw)
    )

    ex: Exchange[Any] = Exchange(in_message=Message(body={}))
    ex.meta.tenant_id = "acme"
    proc = AgentParallelProcessor(
        agents=[
            {"key": "scoring", "workflow_id": "scoring", "prompt_inline": "x"},
            {"key": "antifraud", "workflow_id": "antifraud", "prompt_inline": "y"},
        ]
    )
    await proc.process(ex, context)

    results = ex.get_property("agent_parallel_results")
    assert isinstance(results, dict)
    assert results["scoring"]["content"] == "80"
    assert results["antifraud"]["content"] == "low"
    assert len(gw.calls) == 2


@pytest.mark.asyncio
async def test_continue_on_error_captures_failure(
    monkeypatch: pytest.MonkeyPatch,
    context: ExecutionContext,
) -> None:
    from src.backend.core.config.features import feature_flags

    monkeypatch.setattr(feature_flags, "ai_agent_dsl_enabled", True)
    gw = _FakeAIGateway(
        {"ok_one": AIResponse(content="ok", model_used="m")}
    )
    monkeypatch.setattr(
        AgentRunProcessor, "_resolve_gateway", staticmethod(lambda: gw)
    )

    ex: Exchange[Any] = Exchange()
    proc = AgentParallelProcessor(
        agents=[
            {"key": "ok", "workflow_id": "ok_one", "prompt_inline": "x"},
            {"key": "bad", "workflow_id": "fail_me", "prompt_inline": "y"},
        ],
        continue_on_error=True,
    )
    await proc.process(ex, context)

    results = ex.get_property("agent_parallel_results")
    assert results["ok"]["content"] == "ok"
    assert "error" in results["bad"]


@pytest.mark.asyncio
async def test_feature_flag_off_is_pass_through(
    monkeypatch: pytest.MonkeyPatch,
    context: ExecutionContext,
) -> None:
    from src.backend.core.config.features import feature_flags

    monkeypatch.setattr(feature_flags, "ai_agent_dsl_enabled", False)

    ex: Exchange[Any] = Exchange()
    proc = AgentParallelProcessor(
        agents=[{"key": "a", "workflow_id": "x", "prompt_inline": "y"}]
    )
    await proc.process(ex, context)

    assert ex.get_property("agent_parallel_results") is None


@pytest.mark.asyncio
async def test_custom_result_property(
    monkeypatch: pytest.MonkeyPatch,
    context: ExecutionContext,
) -> None:
    from src.backend.core.config.features import feature_flags

    monkeypatch.setattr(feature_flags, "ai_agent_dsl_enabled", True)
    gw = _FakeAIGateway({"ok": AIResponse(content="r", model_used="m")})
    monkeypatch.setattr(
        AgentRunProcessor, "_resolve_gateway", staticmethod(lambda: gw)
    )

    ex: Exchange[Any] = Exchange()
    proc = AgentParallelProcessor(
        agents=[{"key": "a", "workflow_id": "ok", "prompt_inline": "x"}],
        result_property="parallel_results",
    )
    await proc.process(ex, context)

    assert ex.get_property("parallel_results") is not None
    assert ex.get_property("agent_parallel_results") is None


def test_to_spec_round_trip() -> None:
    proc = AgentParallelProcessor(
        agents=[
            {"key": "a", "workflow_id": "x", "prompt_inline": "p"},
        ],
        result_property="my_res",
        timeout_s=15.0,
        continue_on_error=False,
    )
    spec = proc.to_spec()
    assert spec == {
        "agent_parallel": {
            "agents": [{"key": "a", "workflow_id": "x", "prompt_inline": "p"}],
            "result_property": "my_res",
            "timeout_s": 15.0,
            "continue_on_error": False,
        }
    }
