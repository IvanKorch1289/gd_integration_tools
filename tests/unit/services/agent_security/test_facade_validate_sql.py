"""Тесты AgentSecurityFacade.validate_sql — cycle-5/D-AUDIT-502.

Проверяет, что per-workflow policy override НЕ дропается silently:
при наличии override должен подниматься NotImplementedError.

Без override — обычный passthrough на AgentSecurityFramework.validate_sql.
"""

from __future__ import annotations

import logging

import pytest

from src.backend.core.ai.security import (
    AgentSecurityFramework,
    AgentSecurityPolicy,
    SecurityDecision,
)
from src.backend.services.agent_security.facade import AgentSecurityFacade


@pytest.fixture
def facade() -> AgentSecurityFacade:
    """Fresh facade instance (singleton обходится через прямой __init__)."""
    return AgentSecurityFacade()


def test_validate_sql_without_workflow_id_passes_through(
    facade: AgentSecurityFacade,
) -> None:
    """Без workflow_id — passthrough на framework без ошибок."""
    decision = facade.validate_sql("SELECT * FROM users")
    assert decision.allowed is True


def test_validate_sql_with_workflow_id_no_override_passes_through(
    facade: AgentSecurityFacade,
) -> None:
    """workflow_id задан, но override не зарегистрирован — passthrough."""
    decision = facade.validate_sql("SELECT 1", workflow_id="wf-1")
    assert decision.allowed is True


def test_validate_sql_with_policy_override_raises_not_implemented(
    facade: AgentSecurityFacade, caplog: pytest.LogCaptureFixture
) -> None:
    """policy_override не должен silently дропаться → NotImplementedError.

    Это cycle-5/D-AUDIT-502: раньше facade клал policy_override в kwargs,
    но framework.validate_sql(query) принимает только query — override
    выкидывался без ошибки (security fail-OPEN).
    """
    strict = AgentSecurityPolicy.strict()
    facade.set_policy_for_workflow(strict, "wf-critical")

    with caplog.at_level(logging.ERROR, logger="services.agent_security.facade"):
        with pytest.raises(NotImplementedError) as exc_info:
            facade.validate_sql("SELECT 1", workflow_id="wf-critical")

    assert "policy_override" in str(exc_info.value)
    assert "cycle-5/D-AUDIT-502" in str(exc_info.value)
    assert "wf-critical" in str(exc_info.value)
    # error-лог должен содержать объяснение
    assert any(
        "policy_override dropped" in record.message
        for record in caplog.records
        if record.levelno == logging.ERROR
    )


def test_validate_sql_with_policy_override_blocks_dangerous_sql_via_facade() -> (
    None
):
    """Без override DROP DATABASE блокируется через framework напрямую
    (sanity check, что facade passthrough работает).
    """
    facade = AgentSecurityFacade()
    decision = facade.validate_sql("DROP DATABASE production")
    assert decision.allowed is False
    assert "dangerous_sql" in decision.reason


def test_facade_uses_framework_validate_sql_directly(
    facade: AgentSecurityFacade,
) -> None:
    """Verify that facade.validate_sql без override вызывает именно
    framework.validate_sql(query) (no context kwarg).
    """
    captured: dict[str, object] = {}
    original = AgentSecurityFramework.validate_sql

    def spy(self: AgentSecurityFramework, query: str) -> SecurityDecision:
        captured["query"] = query
        captured["called"] = True
        return original(self, query)

    AgentSecurityFramework.validate_sql = spy  # type: ignore[method-assign]
    try:
        facade.validate_sql("SELECT 42")
    finally:
        AgentSecurityFramework.validate_sql = original  # type: ignore[method-assign]

    assert captured.get("called") is True
    assert captured.get("query") == "SELECT 42"
