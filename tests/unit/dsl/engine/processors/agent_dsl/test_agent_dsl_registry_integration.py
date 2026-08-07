"""D-AGENTS-P1-002 fix (cycle 26): agent_dsl processors registration.

Проверяет, что 6 ключевых agent_dsl processors зарегистрированы
через @processor() decorator в ProcessorRegistry (cycle 26 fix).
"""

# ruff: noqa: S101

from __future__ import annotations

from src.backend.dsl.engine.processors.agent_dsl import (
    agent_branch,
    agent_graph,
    agent_loop,
    agent_parallel,
    agent_run,
    agent_security_check,
)
from src.backend.dsl.registry import get_processor_registry


class TestAgentDSLProcessorsInRegistry:
    """D-AGENTS-P1-002 fix (cycle 26): 6 agent_dsl processors зарегистрированы."""

    EXPECTED_FQNS = [
        ("core:agent_run", ("ai.gateway.invoke",)),
        ("core:agent_branch", ("ai.branch",)),
        ("core:agent_graph", ("ai.invoke",)),
        ("core:agent_loop", ("ai.loop",)),
        ("core:agent_parallel", ("ai.parallel",)),
        ("core:agent_security_check", ("agent.security.check",)),
    ]

    def test_all_six_processors_registered(self) -> None:
        """6 agent_dsl processors зарегистрированы через @processor()."""
        reg = get_processor_registry()
        for fqn, _expected_caps in self.EXPECTED_FQNS:
            assert fqn in reg, (
                f"{fqn} должен быть зарегистрирован (D-AGENTS-P1-002 fix)"
            )

    def test_processors_have_correct_capabilities(self) -> None:
        """Каждый processor имеет capability из EXPECTED_FQNS."""
        reg = get_processor_registry()
        for fqn, expected_caps in self.EXPECTED_FQNS:
            spec = reg.get(fqn)
            assert spec.capabilities == expected_caps, (
                f"{fqn}: capabilities mismatch — expected {expected_caps}, "
                f"got {spec.capabilities}"
            )

    def test_processors_have_spec_schema(self) -> None:
        """Каждый processor имеет non-empty spec_schema (для AsyncAPI/LSP)."""
        reg = get_processor_registry()
        for fqn, _ in self.EXPECTED_FQNS:
            spec = reg.get(fqn)
            assert spec.spec_schema is not None, (
                f"{fqn} должен иметь spec_schema"
            )
            assert spec.spec_schema["type"] == "object", (
                f"{fqn}: spec_schema должен быть JSON-Schema object"
            )

    def test_processors_have_meta_with_tier_and_category(self) -> None:
        """Каждый processor имеет meta с tier/category для docs."""
        reg = get_processor_registry()
        for fqn, _ in self.EXPECTED_FQNS:
            spec = reg.get(fqn)
            assert spec.meta is not None, f"{fqn} должен иметь meta"
            assert spec.meta.get("tier") is not None, (
                f"{fqn}: meta.tier обязателен"
            )
            assert spec.meta.get("category") == "agent", (
                f"{fqn}: meta.category должен быть 'agent'"
            )

    def test_class_imports_succeed(self) -> None:
        """Все 6 модулей импортируются без ошибок (sanity-check)."""
        expected_classes = {
            agent_run: "AgentRunProcessor",
            agent_branch: "AgentBranchProcessor",
            agent_graph: "AgentGraphProcessor",
            agent_loop: "AgentLoopProcessor",
            agent_parallel: "AgentParallelProcessor",
            agent_security_check: "AgentSecurityCheckProcessor",
        }
        for module, class_name in expected_classes.items():
            assert module is not None
            assert hasattr(module, class_name), (
                f"module {module.__name__} должен экспортировать {class_name}"
            )
