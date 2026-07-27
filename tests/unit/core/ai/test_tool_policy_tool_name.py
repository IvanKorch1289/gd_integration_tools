"""Regression tests for P0 tool_name mandatory enforcement (cycle 30).

Reproduces the original vulnerability: tool whitelist bypassed via
``workflow_id`` fallback when ``tool_name`` is absent.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.backend.core.ai.gateway_models import AIRequest


def _make_request(tool_name: str | None = None) -> AIRequest:
    return AIRequest(
        workflow_id="credit_check",
        tenant_id="tenant-1",
        correlation_id="corr-1",
        tool_name=tool_name,
    )


@pytest.mark.unit
def test_whitelist_without_tool_name_raises() -> None:
    """Restricted policy + missing tool_name → ToolPolicyViolationError."""
    from src.backend.core.ai.policy.enforcer.tools_policy import (
        ToolPolicyViolationError,
    )

    policy = MagicMock()
    policy.tools = MagicMock()
    policy.tools.whitelist = ["db.read.orders"]
    policy.tools.blacklist = []
    policy.tools.allow_all_tools = False

    mixin = MagicMock()
    request = _make_request(tool_name=None)

    from src.backend.core.ai.gateway_orchestrator_mixin import EnforcedInvokeMixin

    with pytest.raises(ToolPolicyViolationError, match="tool_name is required"):
        EnforcedInvokeMixin._enforce_tool_policy_once(mixin, request, policy)


@pytest.mark.unit
def test_whitelist_with_valid_tool_name_passes() -> None:
    """Restricted policy + valid tool_name → no raise."""
    policy = MagicMock()
    policy.tools = MagicMock()
    policy.tools.whitelist = ["db.read.orders"]
    policy.tools.blacklist = []
    policy.tools.allow_all_tools = False

    mixin = MagicMock()
    request = _make_request(tool_name="db.read.orders")

    from src.backend.core.ai.gateway_orchestrator_mixin import EnforcedInvokeMixin

    EnforcedInvokeMixin._enforce_tool_policy_once(mixin, request, policy)


@pytest.mark.unit
def test_allow_all_tools_no_tool_name_ok() -> None:
    """allow_all_tools=True + no tool_name → no raise (workflow-level)."""
    policy = MagicMock()
    policy.tools = MagicMock()
    policy.tools.whitelist = []
    policy.tools.blacklist = []
    policy.tools.allow_all_tools = True

    mixin = MagicMock()
    request = _make_request(tool_name=None)

    from src.backend.core.ai.gateway_orchestrator_mixin import EnforcedInvokeMixin

    EnforcedInvokeMixin._enforce_tool_policy_once(mixin, request, policy)


@pytest.mark.unit
def test_no_policy_no_raise() -> None:
    """policy=None → no-op (backward compat)."""
    mixin = MagicMock()
    request = _make_request(tool_name=None)

    from src.backend.core.ai.gateway_orchestrator_mixin import EnforcedInvokeMixin

    EnforcedInvokeMixin._enforce_tool_policy_once(mixin, request, None)
