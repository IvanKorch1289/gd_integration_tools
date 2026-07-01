"""Unit-тесты для AgentToolPolicy wire-up в AgentGraphProcessor (S170 P0-7).

Проверяет, что AgentToolPolicy.check() фильтрует tool_actions на pre-flight
уровне процессора — denied tools не попадают в sandbox.run_react.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.backend.ai.policy import AgentToolPolicy
from src.backend.core.svcs_registry import register_factory
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange, Message
from src.backend.dsl.engine.processors.agent_dsl.agent_graph import AgentGraphProcessor
from src.backend.services.ai.agent_sandbox import AgentSandboxResult


class _FakeSandbox:
    """Capturing sandbox — записывает tool_actions и возвращает success."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def run_react(self, **kwargs: Any) -> AgentSandboxResult:
        self.calls.append(kwargs)
        return AgentSandboxResult(
            success=True, data={"response": "ok"}, backend="fake"
        )

    async def shutdown(self) -> None:
        return None


@pytest.fixture
def exchange() -> Exchange[Any]:
    ex: Exchange[Any] = Exchange(in_message=Message(body={"prompt": "test"}))
    ex.meta.tenant_id = "acme"
    ex.meta.correlation_id = "req-abc-123"
    return ex


@pytest.fixture
def context() -> ExecutionContext:
    return ExecutionContext(route_id="test_route")


class TestAgentGraphToolPolicyWireUp:
    """S170 P0-7: AgentGraphProcessor._run_react фильтрует tools по политике."""

    async def test_all_tools_allowed_pass_through(
        self, exchange: Exchange[Any], context: ExecutionContext
    ) -> None:
        """Если все tools разрешены — sandbox получает полный список."""
        policy = AgentToolPolicy(
            agent_id="permissive", allowed_tools=["db.query", "http.get"], audit_all=False
        )
        register_factory(AgentToolPolicy, lambda: policy)
        try:
            fake = _FakeSandbox()
            proc = AgentGraphProcessor(
                graph_type="react",
                prompt_inline="Find user",
                tool_actions=["db.query", "http.get"],
                sandbox=fake,
                name="test_proc",
            )
            await proc.process(exchange, context)
            assert len(fake.calls) == 1
            assert fake.calls[0]["tool_actions"] == ["db.query", "http.get"]
        finally:
            _reset_policy()

    async def test_denied_tools_filtered_out(
        self, exchange: Exchange[Any], context: ExecutionContext
    ) -> None:
        """Denied tools отфильтровываются, остальные проходят."""
        policy = AgentToolPolicy(
            agent_id="restrictive",
            allowed_tools=["db.query"],
            denied_tools=["http.get"],
            audit_all=False,
        )
        register_factory(AgentToolPolicy, lambda: policy)
        try:
            fake = _FakeSandbox()
            proc = AgentGraphProcessor(
                graph_type="react",
                prompt_inline="Find user",
                tool_actions=["db.query", "http.get"],
                sandbox=fake,
                name="test_proc",
            )
            await proc.process(exchange, context)
            assert len(fake.calls) == 1
            assert fake.calls[0]["tool_actions"] == ["db.query"]
            assert "http.get" not in fake.calls[0]["tool_actions"]  # M2.1: http.get filtered out by policy
        finally:
            _reset_policy()

    async def test_all_tools_denied_returns_error(
        self, exchange: Exchange[Any], context: ExecutionContext
    ) -> None:
        """Если ВСЕ tools denied — return error, sandbox НЕ вызывается."""
        policy = AgentToolPolicy(
            agent_id="strict",
            allowed_tools=[],
            audit_all=False,
        )
        register_factory(AgentToolPolicy, lambda: policy)
        try:
            fake = _FakeSandbox()
            proc = AgentGraphProcessor(
                graph_type="react",
                prompt_inline="Find user",
                tool_actions=["db.query", "http.get"],
                sandbox=fake,
                name="test_proc",
            )
            await proc.process(exchange, context)
            assert all(c.get("durable") is False for c in fake.calls)  # S171 M11 R2: filter check
            result = exchange.get_property("agent_graph_result")
            assert result is not None
            assert "all tools denied" in result["error"]
            assert result["graph_type"] == "react"
        finally:
            _reset_policy()

    async def test_no_policy_registered_no_filtering(
        self, exchange: Exchange[Any], context: ExecutionContext
    ) -> None:
        """Без registered policy — все tools проходят (defensive default)."""
        from src.backend.core.svcs_registry import clear_registry

        clear_registry()
        try:
            fake = _FakeSandbox()
            proc = AgentGraphProcessor(
                graph_type="react",
                prompt_inline="Find user",
                tool_actions=["db.query", "http.get"],
                sandbox=fake,
                name="test_proc",
            )
            await proc.process(exchange, context)
            assert len(fake.calls) == 1
            assert fake.calls[0]["tool_actions"] == ["db.query", "http.get"]
        finally:
            _reset_policy()


def _reset_policy() -> None:
    """Восстанавливает default policy для изоляции тестов."""
    from src.backend.core.svcs_registry import clear_registry, register_factory

    clear_registry()
    register_factory(
        AgentToolPolicy,
        lambda: AgentToolPolicy(agent_id="default", audit_all=False),
    )
