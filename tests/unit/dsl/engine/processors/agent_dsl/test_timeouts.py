"""Tests for ``src.backend.dsl.engine.processors.agent_dsl._timeouts``.

Cycle 13: centralized default timeouts for agent execution.
"""

from __future__ import annotations

from src.backend.dsl.engine.processors.agent_dsl import _timeouts as mod
from src.backend.dsl.engine.processors.agent_dsl._timeouts import (
    DEFAULT_AGENT_TIMEOUT_S,
    DEFAULT_MCP_TIMEOUT_S,
)


class TestDefaultAgentTimeout:
    """DEFAULT_AGENT_TIMEOUT_S — 5 минут (300 секунд)."""

    def test_value_is_300(self) -> None:
        assert DEFAULT_AGENT_TIMEOUT_S == 300.0

    def test_is_float(self) -> None:
        assert isinstance(DEFAULT_AGENT_TIMEOUT_S, float)

    def test_is_positive(self) -> None:
        assert DEFAULT_AGENT_TIMEOUT_S > 0


class TestDefaultMcpTimeout:
    """DEFAULT_MCP_TIMEOUT_S — 30 секунд."""

    def test_value_is_30(self) -> None:
        assert DEFAULT_MCP_TIMEOUT_S == 30.0

    def test_is_float(self) -> None:
        assert isinstance(DEFAULT_MCP_TIMEOUT_S, float)

    def test_is_positive(self) -> None:
        assert DEFAULT_MCP_TIMEOUT_S > 0


class TestTimeoutsRelationship:
    """Agent timeout >> MCP timeout (per D421 design)."""

    def test_agent_timeout_longer_than_mcp(self) -> None:
        # Agent execution может включать несколько MCP calls
        assert DEFAULT_AGENT_TIMEOUT_S > DEFAULT_MCP_TIMEOUT_S

    def test_agent_timeout_is_10x_mcp(self) -> None:
        # 300 / 30 = 10
        assert DEFAULT_AGENT_TIMEOUT_S == DEFAULT_MCP_TIMEOUT_S * 10


class TestAllExports:
    """__all__ проверка."""

    def test_exports_two_constants(self) -> None:
        assert "DEFAULT_AGENT_TIMEOUT_S" in mod.__all__
        assert "DEFAULT_MCP_TIMEOUT_S" in mod.__all__
        assert len(mod.__all__) == 2

    def test_constants_importable_from_module(self) -> None:
        # Можно импортировать оба константы
        from src.backend.dsl.engine.processors.agent_dsl._timeouts import (
            DEFAULT_AGENT_TIMEOUT_S as a,
            DEFAULT_MCP_TIMEOUT_S as m,
        )

        assert a == DEFAULT_AGENT_TIMEOUT_S
        assert m == DEFAULT_MCP_TIMEOUT_S


class TestModuleImport:
    """Smoke import."""

    def test_module_imports(self) -> None:
        from src.backend.dsl.engine.processors.agent_dsl import _timeouts as m

        assert m is mod

    def test_module_has_docstring(self) -> None:
        # Module docstring с упоминанием D421
        assert mod.__doc__ is not None
        assert "D421" in mod.__doc__ or "timeout" in mod.__doc__.lower()