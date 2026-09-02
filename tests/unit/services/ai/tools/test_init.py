"""Unit-тесты ``services.ai.tools`` — coverage ratchet (Post-Plan A Sprint 18).

core/ai/tools service package facade (ToolRegistry): re-exports 4 symbols
(AgentTool dataclass, ToolRegistry class, agent_tool decorator,
get_tool_registry singleton getter). ~6 stmts, 0% coverage.

Цель slice: 0% → 100% через __all__ audit + class/callable identity.
"""

from __future__ import annotations

import pytest

from src.backend.services.ai import tools
from src.backend.services.ai.tools import (
    AgentTool,
    ToolRegistry,
    agent_tool,
    get_tool_registry,
)


@pytest.mark.unit
class TestToolsFacadeAllExports:
    """``__all__`` audit + class/callable identity."""

    @pytest.mark.parametrize(
        "symbol_name",
        ["AgentTool", "ToolRegistry", "agent_tool", "get_tool_registry"],
    )
    def test_all_exports_accessible(self, symbol_name: str) -> None:
        """Каждый символ из ``__all__`` доступен через facade."""
        assert hasattr(tools, symbol_name), (
            f"Missing export: {symbol_name}"
        )
        assert symbol_name in tools.__all__, (
            f"{symbol_name} not declared in __all__"
        )

    def test_all_declared_count(self) -> None:
        """``__all__`` содержит 4 символа."""
        assert len(tools.__all__) == 4

    def test_module_docstring_present(self) -> None:
        """Module docstring описывает ToolRegistry (AI tool registry)."""
        assert tools.__doc__ is not None
        assert "Tool" in tools.__doc__ or "tool" in tools.__doc__.lower()


@pytest.mark.unit
class TestToolsFacadeIdentity:
    """Identity checks для 4 re-exports."""

    def test_agent_tool_is_class(self) -> None:
        """``AgentTool`` — class (dataclass / Pydantic model)."""
        assert isinstance(AgentTool, type)

    def test_tool_registry_is_class(self) -> None:
        """``ToolRegistry`` — class (registry)."""
        assert isinstance(ToolRegistry, type)

    def test_agent_tool_decorator_is_callable(self) -> None:
        """``agent_tool`` — callable (decorator)."""
        assert callable(agent_tool)

    def test_get_tool_registry_is_callable(self) -> None:
        """``get_tool_registry`` — callable (singleton getter)."""
        assert callable(get_tool_registry)
