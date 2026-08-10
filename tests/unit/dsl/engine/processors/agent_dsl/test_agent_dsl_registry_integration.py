"""D-AGENTS-P1-002 fix (cycle 26+27): agent_dsl processors registration.

Проверяет, что 19 ключевых agent_dsl processors зарегистрированы
через @processor() decorator в ProcessorRegistry.
"""


from __future__ import annotations

from src.backend.dsl.engine.processors.agent_dsl import (
    agent_branch,
    agent_graph,
    agent_loop,
    agent_parallel,
    agent_pii_mask,
    agent_run,
    agent_security_check,
    ai_tool_dispatch,
    bind_skill,
    guardrails_apply,
    langgraph_agent,
    mcp_tool,
    memory_recall,
    memory_store,
    pii_mask,
    pii_unmask,
    plan_execute,
    reflection_loop,
    skill_invoke,
)
from src.backend.dsl.registry import get_processor_registry


class TestAgentDSLProcessorsInRegistry:
    """D-AGENTS-P1-002 fix (cycle 26+27): 19 agent_dsl processors зарегистрированы."""

    EXPECTED_FQNS = [
        ("core:agent_run", ("ai.gateway.invoke",)),
        ("core:agent_branch", ("ai.branch",)),
        ("core:agent_graph", ("ai.invoke",)),
        ("core:agent_loop", ("ai.loop",)),
        ("core:agent_parallel", ("ai.parallel",)),
        ("core:agent_security_check", ("agent.security.check",)),
        ("core:agent_pii_mask", ("agent.pii.mask",)),
        ("core:ai_tool_dispatch", ("ai.tool.dispatch",)),
        ("core:bind_skill", ("skill.bind",)),
        ("core:guardrails_apply", ("guardrails.apply",)),
        ("core:langgraph_agent", ("ai.langgraph.invoke",)),
        ("core:mcp_tool", ("mcp.tool.invoke",)),
        ("core:memory_recall", ("memory.recall",)),
        ("core:memory_store", ("memory.store",)),
        ("core:pii_mask", ("pii.mask",)),
        ("core:pii_unmask", ("pii.unmask",)),
        ("core:plan_execute", ("agent.plan",)),
        ("core:reflection_loop", ("agent.reflect",)),
        ("core:skill_invoke", ("skill.invoke",)),
    ]

    def test_all_nineteen_processors_registered(self) -> None:
        """19 agent_dsl processors зарегистрированы через @processor()."""
        reg = get_processor_registry()
        for fqn, _ in self.EXPECTED_FQNS:
            assert fqn in reg, f"{fqn} должен быть зарегистрирован"

    def test_processors_have_correct_capabilities(self) -> None:
        """Каждый processor имеет capability из EXPECTED_FQNS."""
        reg = get_processor_registry()
        for fqn, expected_caps in self.EXPECTED_FQNS:
            spec = reg.get(fqn)
            assert spec.capabilities == expected_caps, (
                f"{fqn}: expected {expected_caps}, got {spec.capabilities}"
            )

    def test_processors_have_spec_schema(self) -> None:
        """Каждый processor имеет non-empty spec_schema (JSON-Schema)."""
        reg = get_processor_registry()
        for fqn, _ in self.EXPECTED_FQNS:
            spec = reg.get(fqn)
            assert spec.spec_schema is not None
            assert spec.spec_schema["type"] == "object"

    def test_processors_have_meta_with_tier_and_category(self) -> None:
        """Каждый processor имеет meta с tier/category для docs."""
        reg = get_processor_registry()
        for fqn, _ in self.EXPECTED_FQNS:
            spec = reg.get(fqn)
            assert spec.meta is not None
            assert spec.meta.get("tier") is not None
            assert spec.meta.get("category") == "agent"

    def test_all_modules_importable(self) -> None:
        """19 модулей импортируются без ошибок (sanity-check)."""
        expected_modules = (
            agent_run, agent_branch, agent_graph, agent_loop,
            agent_parallel, agent_security_check, agent_pii_mask,
            ai_tool_dispatch, bind_skill, guardrails_apply, langgraph_agent,
            mcp_tool, memory_recall, memory_store, pii_mask, pii_unmask,
            plan_execute, reflection_loop, skill_invoke,
        )
        assert len(expected_modules) == 19
        for module in expected_modules:
            assert module is not None
