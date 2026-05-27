"""Smoke-тесты OrchestratorSpec и OrchestratorEngine (S28 W4).

Проверяют:
* OrchestratorSpec Pydantic validation;
* RoutingRule JMESPath evaluation;
* OrchestratorEngine.route() с feature-flag и fallback.
"""

from __future__ import annotations

import pytest

from src.backend.core.ai.agent_registry import AgentRegistry
from src.backend.core.ai.agent_spec import AgentSpec
from src.backend.dsl.workflow.orchestrator import OrchestratorSpec, RoutingRule
from src.backend.dsl.workflow.orchestrator_engine import OrchestratorEngine


def test_orchestrator_spec_minimal() -> None:
    """OrchestratorSpec с минимальными required полями."""
    spec = OrchestratorSpec(name="credit_orchestrator")
    assert spec.name == "credit_orchestrator"
    assert spec.pattern == "orchestrator-subagent"
    assert spec.routing == []
    assert spec.default_agent is None


def test_orchestrator_spec_full() -> None:
    """OrchestratorSpec с полным набором опций."""
    spec = OrchestratorSpec(
        name="credit_orchestrator",
        pattern="supervisor",
        routing=[
            RoutingRule(
                when="body.type == 'score'",
                use_agent="score_agent",
                use_model="minimax:m2.5",
            ),
            RoutingRule(
                when="body.type == 'approval'",
                use_agent="approval_agent",
            ),
        ],
        default_agent="generalist",
        fallback_agent="fallback_agent",
    )
    assert spec.pattern == "supervisor"
    assert len(spec.routing) == 2
    assert spec.routing[0].use_model == "minimax:m2.5"
    assert spec.default_agent == "generalist"


def test_routing_rule_defaults() -> None:
    """RoutingRule с defaults."""
    rule = RoutingRule(when="body.type == 'score'")
    assert rule.use_agent is None
    assert rule.use_model is None
    assert rule.memory_scope is None


def test_orchestrator_engine_route_first_rule_matches(
    agent_registry: AgentRegistry,
) -> None:
    """route() возвращает agent по первому matching rule."""
    engine = OrchestratorEngine(registry=agent_registry)
    spec = OrchestratorSpec(
        name="test",
        routing=[
            RoutingRule(when="input.type == 'score'", use_agent="score_agent"),
            RoutingRule(when="input.type == 'approval'", use_agent="approval_agent"),
        ],
        default_agent="default_agent",
    )
    result = engine.route(
        task={"input": {"type": "score"}},
        orchestrator_spec=spec,
    )
    assert result.target_agent.id == "score_agent"
    assert result.matched_rule == 0


def test_orchestrator_engine_route_second_rule_matches(
    agent_registry: AgentRegistry,
) -> None:
    """route() возвращает agent по второму matching rule."""
    engine = OrchestratorEngine(registry=agent_registry)
    spec = OrchestratorSpec(
        name="test",
        routing=[
            RoutingRule(when="input.type == 'score'", use_agent="score_agent"),
            RoutingRule(when="input.type == 'approval'", use_agent="approval_agent"),
        ],
    )
    result = engine.route(
        task={"input": {"type": "approval"}},
        orchestrator_spec=spec,
    )
    assert result.target_agent.id == "approval_agent"
    assert result.matched_rule == 1


def test_orchestrator_engine_route_no_match_uses_default(
    agent_registry: AgentRegistry,
) -> None:
    """route() использует default_agent когда ни одно правило не сработало."""
    engine = OrchestratorEngine(registry=agent_registry)
    spec = OrchestratorSpec(
        name="test",
        routing=[
            RoutingRule(when="input.type == 'score'", use_agent="score_agent"),
        ],
        default_agent="default_agent",
    )
    result = engine.route(
        task={"input": {"type": "unknown"}},
        orchestrator_spec=spec,
    )
    assert result.target_agent.id == "default_agent"
    assert result.matched_rule is None


def test_orchestrator_engine_route_raises_on_no_default(
    agent_registry: AgentRegistry,
) -> None:
    """route() raises ValueError когда ни одно правило не сработало и default_agent нет."""
    engine = OrchestratorEngine(registry=agent_registry)
    spec = OrchestratorSpec(
        name="test",
        routing=[
            RoutingRule(when="input.type == 'score'", use_agent="score_agent"),
        ],
    )
    with pytest.raises(ValueError, match="no routing rule matched"):
        engine.route(task={"input": {"type": "unknown"}}, orchestrator_spec=spec)


def test_orchestrator_engine_rule_model_override(
    agent_registry: AgentRegistry,
) -> None:
    """route() применяет use_model override из routing rule."""
    engine = OrchestratorEngine(registry=agent_registry)
    spec = OrchestratorSpec(
        name="test",
        routing=[
            RoutingRule(
                when="input.type == 'score'",
                use_agent="score_agent",
                use_model="openai:gpt-4o",
            ),
        ],
    )
    result = engine.route(
        task={"input": {"type": "score"}},
        orchestrator_spec=spec,
    )
    assert result.target_model == "openai:gpt-4o"


# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def agent_registry() -> AgentRegistry:
    """Создать AgentRegistry с двумя агентами для тестов."""
    registry = AgentRegistry()
    registry.register(
        AgentSpec(id="score_agent", version="1.0.0", model="minimax:m2")
    )
    registry.register(
        AgentSpec(id="approval_agent", version="1.0.0", model="minimax:m2")
    )
    registry.register(
        AgentSpec(id="default_agent", version="1.0.0", model="minimax:m2")
    )
    return registry