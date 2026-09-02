"""Unit-тесты ``services.ai.multi_agent`` — coverage ratchet (Post-Plan A Sprint 21).

core/ai/multi_agent service package facade (K4 Sprint 7): re-exports 4 symbols
(MultiAgentSupervisor class + AgentSpec dataclass + get_credit_pipeline_supervisor
singleton getter + MultiAgentSupervisorUnavailable Exception). ~6 stmts, 0%.

Цель slice: 0% → 100% через __all__ audit + class/callable identity.
"""

from __future__ import annotations

import pytest

from src.backend.services.ai import multi_agent
from src.backend.services.ai.multi_agent import (
    AgentSpec,
    MultiAgentSupervisor,
    MultiAgentSupervisorUnavailable,
    get_credit_pipeline_supervisor,
)


@pytest.mark.unit
class TestMultiAgentFacadeAllExports:
    """``__all__`` audit + class/callable identity."""

    @pytest.mark.parametrize(
        "symbol_name",
        [
            "AgentSpec",
            "MultiAgentSupervisor",
            "MultiAgentSupervisorUnavailable",
            "get_credit_pipeline_supervisor",
        ],
    )
    def test_all_exports_accessible(self, symbol_name: str) -> None:
        """Каждый символ из ``__all__`` доступен через facade."""
        assert hasattr(multi_agent, symbol_name), (
            f"Missing export: {symbol_name}"
        )
        assert symbol_name in multi_agent.__all__, (
            f"{symbol_name} not declared in __all__"
        )

    def test_all_declared_count(self) -> None:
        """``__all__`` содержит 4 символа."""
        assert len(multi_agent.__all__) == 4

    def test_module_docstring_present(self) -> None:
        """Module docstring описывает multi-agent supervisor (K4 Sprint 7)."""
        assert multi_agent.__doc__ is not None
        assert "supervisor" in multi_agent.__doc__.lower() or "multi-agent" in multi_agent.__doc__.lower()


@pytest.mark.unit
class TestMultiAgentFacadeIdentity:
    """Identity checks для 4 re-exports."""

    def test_multi_agent_supervisor_is_class(self) -> None:
        """``MultiAgentSupervisor`` — class (LangGraph supervisor)."""
        assert isinstance(MultiAgentSupervisor, type)

    def test_agent_spec_is_class(self) -> None:
        """``AgentSpec`` — class (dataclass)."""
        assert isinstance(AgentSpec, type)

    def test_get_credit_pipeline_supervisor_is_callable(self) -> None:
        """``get_credit_pipeline_supervisor`` — callable (singleton getter)."""
        assert callable(get_credit_pipeline_supervisor)

    def test_multi_agent_supervisor_unavailable_is_exception(self) -> None:
        """``MultiAgentSupervisorUnavailable`` — Exception subclass."""
        assert isinstance(MultiAgentSupervisorUnavailable, type)
        assert issubclass(MultiAgentSupervisorUnavailable, Exception)
