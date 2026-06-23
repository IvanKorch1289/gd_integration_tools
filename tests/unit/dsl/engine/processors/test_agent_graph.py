"""Unit-тесты AgentGraphProcessor (S133 W4).

Покрытие:
    * ReAct mode через in-process sandbox.
    * ReAct mode через фейковый sandbox (isolation boundary).
    * to_spec сериализует isolated.
"""

# ruff: noqa: S101

from __future__ import annotations

from typing import Any

import pytest

from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange, Message
from src.backend.dsl.engine.processors.agent_dsl.agent_graph import AgentGraphProcessor
from src.backend.services.ai.agent_sandbox import AgentSandboxResult


def _exchange(body: Any = None, correlation_id: str = "cid-1") -> Exchange[Any]:
    ex = Exchange(in_message=Message(body=body, headers={}), properties={})
    ex.meta.correlation_id = correlation_id
    return ex


class _FakeSandbox:
    """Фейковый sandbox для проверки isolation boundary."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def run_react(
        self,
        *,
        prompt: str,
        tool_actions: list[str],
        model: str,
        temperature: float,
        durable: bool,
        session_id: str | None,
    ) -> AgentSandboxResult:
        self.calls.append(
            {
                "prompt": prompt,
                "tool_actions": tool_actions,
                "model": model,
                "session_id": session_id,
            }
        )
        return AgentSandboxResult(
            success=True,
            data={"response": "fake-isolated", "tools_used": tool_actions},
            backend="fake",
        )

    async def shutdown(self) -> None:
        pass


@pytest.mark.asyncio
async def test_react_in_process(monkeypatch: pytest.MonkeyPatch) -> None:
    """ReAct без sandbox использует build_and_run_agent in-process."""
    calls: list[dict[str, Any]] = []

    async def _fake_build_and_run_agent(**kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs)
        return {"response": "ok-in-process"}

    monkeypatch.setattr(
        "src.backend.services.ai.ai_graph.build_and_run_agent",
        _fake_build_and_run_agent,
    )

    proc = AgentGraphProcessor(
        graph_type="react",
        prompt_inline="Do something",
        tool_actions=["db.query"],
        model="gpt-4o",
    )
    ex = _exchange(body={"user_input": "ctx"})
    ctx = ExecutionContext(route_id="r-1")
    await proc._run(ex, ctx)

    assert ex.properties["agent_graph_result"]["response"] == "ok-in-process"
    assert calls[0]["prompt"].startswith("Do something")
    assert calls[0]["tool_actions"] == ["db.query"]
    assert calls[0]["model"] == "gpt-4o"
    assert calls[0]["session_id"] == "cid-1"


@pytest.mark.asyncio
async def test_react_isolated_uses_sandbox() -> None:
    """ReAct с фейковым sandbox не вызывает in-process build_and_run_agent."""
    fake = _FakeSandbox()
    proc = AgentGraphProcessor(
        graph_type="react",
        prompt_inline="Do something",
        tool_actions=["db.query"],
        model="gpt-4o",
        sandbox=fake,
        isolated=True,
    )
    ex = _exchange(body={"user_input": "ctx"})
    ctx = ExecutionContext(route_id="r-1")
    await proc._run(ex, ctx)

    assert len(fake.calls) == 1
    assert fake.calls[0]["prompt"].startswith("Do something")
    assert fake.calls[0]["tool_actions"] == ["db.query"]
    assert fake.calls[0]["model"] == "gpt-4o"
    assert fake.calls[0]["session_id"] == "cid-1"
    assert ex.properties["agent_graph_result"]["response"] == "fake-isolated"


def test_to_spec_serializes_isolated() -> None:
    """to_spec включает isolated=True если задан."""
    proc = AgentGraphProcessor(
        graph_type="react",
        prompt_inline="Do something",
        tool_actions=["db.query"],
        isolated=True,
    )
    spec = proc.to_spec()
    assert spec["agent_graph"]["isolated"] is True


def test_to_spec_omits_isolated_default() -> None:
    """to_spec не включает isolated при default False."""
    proc = AgentGraphProcessor(
        graph_type="react", prompt_inline="Do something", tool_actions=["db.query"]
    )
    spec = proc.to_spec()
    assert "isolated" not in spec["agent_graph"]


def test_isolated_true_uses_process_pool_sandbox() -> None:
    """S3 fix (S36-W15): isolated=True default → ProcessPoolAgentSandbox.

    Pre-fix: ``sandbox or InProcessAgentSandbox()`` игнорировал isolated
    flag → zero-isolation по умолчанию. Теперь: isolated=True →
    ProcessPoolAgentSandbox.
    """
    from src.backend.services.ai.agent_sandbox import ProcessPoolAgentSandbox

    proc = AgentGraphProcessor(
        graph_type="react",
        prompt_inline="test",
        tool_actions=["db.query"],
        isolated=True,
    )
    assert isinstance(proc._sandbox, ProcessPoolAgentSandbox)


def test_isolated_false_explicit_uses_inprocess_sandbox() -> None:
    """S3 fix: isolated=False explicit opt-in → InProcessAgentSandbox."""
    from src.backend.services.ai.agent_sandbox import InProcessAgentSandbox

    proc = AgentGraphProcessor(
        graph_type="react",
        prompt_inline="test",
        tool_actions=["db.query"],
        isolated=False,
    )
    assert isinstance(proc._sandbox, InProcessAgentSandbox)


def test_explicit_sandbox_overrides_isolated() -> None:
    """S3 fix: caller-инжектированный sandbox имеет приоритет над isolated flag."""
    proc = AgentGraphProcessor(
        graph_type="react",
        prompt_inline="test",
        tool_actions=["db.query"],
        sandbox=_FakeSandbox(),
        isolated=True,  # even with isolated=True, explicit sandbox wins
    )
    assert proc._sandbox.__class__.__name__ == "_FakeSandbox"
