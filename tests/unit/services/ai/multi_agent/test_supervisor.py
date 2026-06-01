"""Unit-тесты MultiAgentSupervisor (K4 Sprint 7).

Покрывают:
1. default-OFF: supervisor.run() возвращает stub при выключенном flag.
2. Fallback router: при отсутствии langgraph каждый агент вызывается один раз.
3. Reference credit-pipeline supervisor: 3 stub-агента в правильном порядке.
4. Дубликаты/пустые списки агентов → ValueError.
5. AgentSpec.call с None invoke → stub-результат.
"""

from __future__ import annotations

import sys
from typing import Any

import pytest

from src.backend.services.ai.multi_agent import (
    AgentSpec,
    MultiAgentSupervisor,
    get_credit_pipeline_supervisor,
)


@pytest.mark.asyncio
async def test_supervisor_disabled_returns_stub(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """При выключенном feature_flag .run() возвращает stub без вызовов агентов."""
    from src.backend.core.config.features import feature_flags

    monkeypatch.setattr(
        feature_flags, "multi_agent_supervisor_enabled", False, raising=False
    )
    sup = MultiAgentSupervisor(
        name="test_supervisor",
        agents=[AgentSpec(name="a1", description="agent 1")],
    )
    result = await sup.run(prompt="hello")
    assert result["supervisor"] == "test_supervisor"
    assert result["agents_invoked"] == []
    assert result["error"] is not None
    assert "disabled" in result["final_response"]


@pytest.mark.asyncio
async def test_supervisor_fallback_router_invokes_all_agents(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """При отсутствии langgraph fallback вызывает все агенты ровно один раз."""
    # Имитируем отсутствие langgraph.
    monkeypatch.setitem(sys.modules, "langgraph", None)

    calls: list[str] = []

    async def _make_invoke(name: str) -> Any:
        async def _inner(payload: dict[str, Any]) -> dict[str, Any]:
            calls.append(name)
            return {"agent": name, "ok": True}

        return _inner

    agents = [
        AgentSpec(name="a1", description="first", invoke=await _make_invoke("a1")),
        AgentSpec(name="a2", description="second", invoke=await _make_invoke("a2")),
        AgentSpec(name="a3", description="third", invoke=await _make_invoke("a3")),
    ]
    sup = MultiAgentSupervisor(name="s1", agents=agents, enabled=True)
    result = await sup.run(prompt="task", payload={"k": "v"})

    assert calls == ["a1", "a2", "a3"]
    assert result["agents_invoked"] == ["a1", "a2", "a3"]
    assert result["used_langgraph"] is False
    assert len(result["outputs"]) == 3
    assert all(out["ok"] for out in result["outputs"])


@pytest.mark.asyncio
async def test_credit_pipeline_supervisor_smoke(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reference credit-pipeline supervisor вызывает 3 агента и возвращает approved=True."""
    monkeypatch.setitem(sys.modules, "langgraph", None)
    sup = get_credit_pipeline_supervisor(enabled=True)
    assert sup.name == "credit_orchestrator"
    assert sup.agent_names == ("scoring_agent", "document_parser_agent", "decision_agent")

    result = await sup.run(prompt="Оцени заявку", payload={"client_id": 12345})
    assert result["agents_invoked"] == [
        "scoring_agent",
        "document_parser_agent",
        "decision_agent",
    ]
    # decision_agent видит scoring_agent output и одобряет (score=750 >= 600).
    decision = next(o for o in result["outputs"] if o["agent"] == "decision_agent")
    assert decision["approved"] is True


@pytest.mark.asyncio
async def test_supervisor_validation_errors() -> None:
    """Пустой список агентов и дубликаты имён → ValueError."""
    with pytest.raises(ValueError, match="хотя бы одного"):
        MultiAgentSupervisor(name="empty", agents=[])

    dupe = [
        AgentSpec(name="a", description="x"),
        AgentSpec(name="a", description="y"),
    ]
    with pytest.raises(ValueError, match="Дубликат"):
        MultiAgentSupervisor(name="dupe", agents=dupe)


@pytest.mark.asyncio
async def test_agent_spec_none_invoke_returns_stub() -> None:
    """AgentSpec.call с invoke=None возвращает stub-словарь."""
    spec = AgentSpec(name="stub_agent", description="без invoke")
    output = await spec.call({"key": "value"})
    assert output["agent"] == "stub_agent"
    assert output["stub"] is True
    assert output["payload"] == {"key": "value"}
