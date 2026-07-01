"""Unit tests for AgentToolPolicy (S169/S170 quick wins).

S169 создал ``src/backend/ai/policy/tool_policy.py`` с AgentToolPolicy Pydantic
моделью и default-deny semantics. S170 B016-batch добавил tests (audit gap:
«No tests for the new AgentToolPolicy exist»).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.backend.ai.policy import AgentToolPolicy, ToolPermission


class TestToolPermissionEnum:
    def test_enum_values(self) -> None:
        assert ToolPermission.ALLOW.value == "allow"
        assert ToolPermission.DENY.value == "deny"
        assert ToolPermission.AUDIT.value == "audit"

    def test_enum_string_inheritance(self) -> None:
        # str-inheritance позволяет использовать enum как Pydantic value
        assert isinstance(ToolPermission.ALLOW, str)
        assert ToolPermission.ALLOW == "allow"


class TestAgentToolPolicyBasic:
    def test_minimal_valid(self) -> None:
        p = AgentToolPolicy(agent_id="test", allowed_tools=["foo", "bar"])
        assert p.agent_id == "test"
        assert p.allowed_tools == ["foo", "bar"]
        assert p.denied_tools == []
        assert p.audit_all is True
        assert p.max_tool_calls_per_run == 50

    def test_defaults_applied(self) -> None:
        p = AgentToolPolicy(agent_id="minimal", allowed_tools=["x"])
        assert p.denied_tools == []
        assert p.audit_all is True
        assert p.max_tool_calls_per_run == 50

    def test_allowed_tools_default_empty(self) -> None:
        # allowed_tools опционален (default_factory=list), strict-режим
        p = AgentToolPolicy(agent_id="strict")
        assert p.allowed_tools == []

    def test_missing_agent_id_raises(self) -> None:
        with pytest.raises(ValidationError):
            AgentToolPolicy(allowed_tools=["x"])  # type: ignore[call-arg]

    def test_empty_allowed_tools_allowed(self) -> None:
        # Default-deny mode: пустой allowed_tools → всё запрещено
        p = AgentToolPolicy(agent_id="strict", allowed_tools=[])
        assert p.check("anything") == ToolPermission.DENY


class TestAgentToolPolicyCheck:
    """Тесты default-deny semantics."""

    def test_denied_tool_returns_deny_even_if_allowed(self) -> None:
        """denied_tools имеет приоритет над allowed_tools."""
        p = AgentToolPolicy(
            agent_id="test",
            allowed_tools=["foo", "bar"],
            denied_tools=["foo"],
        )
        assert p.check("foo") == ToolPermission.DENY

    def test_allowed_tool_with_audit_all_returns_audit(self) -> None:
        p = AgentToolPolicy(
            agent_id="test",
            allowed_tools=["foo"],
            audit_all=True,
        )
        assert p.check("foo") == ToolPermission.AUDIT

    def test_allowed_tool_without_audit_all_returns_allow(self) -> None:
        p = AgentToolPolicy(
            agent_id="test",
            allowed_tools=["foo"],
            audit_all=False,
        )
        assert p.check("foo") == ToolPermission.ALLOW

    def test_unknown_tool_returns_deny(self) -> None:
        p = AgentToolPolicy(agent_id="test", allowed_tools=["foo"])
        assert p.check("unknown") == ToolPermission.DENY

    def test_empty_allowed_denies_everything(self) -> None:
        p = AgentToolPolicy(agent_id="strict", allowed_tools=[])
        assert p.check("foo") == ToolPermission.DENY
        assert p.check("anything") == ToolPermission.DENY


class TestAgentToolPolicyRuntimeTracking:
    """Tests для call-counter logic.

    С `audit_all=False` check возвращает ALLOW, и `is_allowed()` → True.
    С `audit_all=True` (default) check возвращает AUDIT, и `is_allowed()`
    → False (нужен явный AUDIT-handler).
    """

    def _policy(self, **kwargs: object) -> AgentToolPolicy:
        defaults: dict[str, object] = {
            "agent_id": "test",
            "allowed_tools": ["foo"],
            "audit_all": False,  # для тестов is_allowed (True only on ALLOW)
        }
        defaults.update(kwargs)
        return AgentToolPolicy(**defaults)  # type: ignore[arg-type]

    def test_initial_call_count_zero(self) -> None:
        p = self._policy()
        assert p.is_allowed("foo") is True  # 0 < 50

    def test_call_count_increments(self) -> None:
        p = self._policy()
        assert p.is_allowed("foo") is True  # 1
        assert p.is_allowed("foo") is True  # 2
        assert p.is_allowed("foo") is True  # 3

    def test_call_count_over_limit_denies(self) -> None:
        p = self._policy(max_tool_calls_per_run=2)
        assert p.is_allowed("foo") is True  # 1
        assert p.is_allowed("foo") is True  # 2
        assert p.is_allowed("foo") is False  # 3 — превышен лимит

    def test_reset_run_clears_counter(self) -> None:
        p = self._policy(max_tool_calls_per_run=2)
        p.is_allowed("foo")  # 1
        p.is_allowed("foo")  # 2
        assert p.is_allowed("foo") is False  # 3 — лимит

        p.reset_run()
        assert p.is_allowed("foo") is True  # counter reset

    def test_denied_tool_always_blocked_regardless_of_count(self) -> None:
        p = AgentToolPolicy(
            agent_id="test",
            allowed_tools=["foo"],
            denied_tools=["bar"],
            max_tool_calls_per_run=2,
        )
        assert p.is_allowed("bar") is False
        assert p.is_allowed("bar") is False


class TestAgentToolPolicyIntegration:
    """Интеграция с svcs_registry DI."""

    def test_di_factory_returns_default_policy(self) -> None:
        from src.backend.core.svcs_registry import get_service, register_factory

        # get_service должен вернуть default AgentToolPolicy instance
        policy = get_service(AgentToolPolicy)
        assert isinstance(policy, AgentToolPolicy)
        assert policy.agent_id == "default"

    def test_re_register_factory(self) -> None:
        from src.backend.core.svcs_registry import (
            get_service,
            register_factory,
        )

        # Custom factory
        custom = AgentToolPolicy(
            agent_id="custom_agent", allowed_tools=["search"]
        )
        register_factory(AgentToolPolicy, lambda: custom)
        assert get_service(AgentToolPolicy) is custom