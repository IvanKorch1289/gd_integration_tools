"""Regression test for D-A7-02 (MCPToolProcessor shadow fix).

D-AUDIT-04 (cycle 1): дубликаты ``MCPToolProcessor`` и ``AgentGraphProcessor``
были удалены из ``src/backend/dsl/engine/processors/external.py``, потому что:

- ``MCPToolProcessor`` — отсутствовал protocol validation (``file://`` attack surface);
- ``AgentGraphProcessor`` — нарушал layer boundary (``dsl`` → ``services.ai.ai_graph``).

Canonical классы живут в ``agent_dsl/mcp_tool.py:68`` и ``agent_dsl/agent_graph.py:98``.

Тест фиксирует инвариант: ``external`` экспортирует ТОЛЬКО ``CDCProcessor``
и НЕ должен re-shadowed канонические AI-процессоры.
"""

from __future__ import annotations

from src.backend.dsl.engine.processors import external


def test_external_exports_only_cdc_processor() -> None:
    """``external.__all__`` содержит только ``CDCProcessor``."""
    assert tuple(external.__all__) == ("CDCProcessor",)


def test_external_has_no_mcp_tool_processor_shadow() -> None:
    """``MCPToolProcessor`` НЕ должен жить в ``external`` (canonical: agent_dsl/mcp_tool.py)."""
    assert not hasattr(external, "MCPToolProcessor")


def test_external_has_no_agent_graph_processor_shadow() -> None:
    """``AgentGraphProcessor`` НЕ должен жить в ``external`` (canonical: agent_dsl/agent_graph.py)."""
    assert not hasattr(external, "AgentGraphProcessor")


def test_external_cdc_processor_is_importable() -> None:
    """``CDCProcessor`` остаётся доступен из ``external``."""
    assert hasattr(external, "CDCProcessor")
    cls = external.CDCProcessor
    assert cls.__name__ == "CDCProcessor"
    assert cls.__module__ == "src.backend.dsl.engine.processors.external"
