"""Unit-тесты для S209 fail-closed tool policy (security fix).

Проверяет:
* Empty whitelist+blacklist + allow_all_tools=False (default) → fail-closed.
* Empty whitelist+blacklist + allow_all_tools=True → backward-compat allow.
* Non-empty whitelist → normal enforcement.
"""

from __future__ import annotations

import pytest

from src.backend.core.ai.gateway_models import AIRequest
from src.backend.core.ai.gateway_orchestrator_mixin import EnforcedInvokeMixin
from src.backend.core.ai.policy.enforcer.tools_policy import (
    ToolPolicyViolationError,
)
from src.backend.core.ai.policy.spec import ToolsSpec


class _StubGateway(EnforcedInvokeMixin):
    """Минимальный stub для доступа к protected method через MRO."""


def _make_request(workflow_id: str = "wf-1") -> AIRequest:
    return AIRequest(
        workflow_id=workflow_id,
        tenant_id="tenant-1",
        correlation_id="corr-1",
        prompt_inline="test",
    )


class TestS209FailClosed:
    """S209: пустые whitelist+blacklist → deny-all by default."""

    def test_empty_lists_no_optin_raises(self) -> None:
        """Default: empty lists без allow_all_tools → ToolPolicyViolationError."""
        gw = _StubGateway()
        policy = type("P", (), {"tools": ToolsSpec()})()
        with pytest.raises(ToolPolicyViolationError, match="deny-all by default"):
            gw._enforce_tool_policy_once(_make_request(), policy)

    def test_empty_lists_with_optin_allows(self) -> None:
        """Backward-compat: allow_all_tools=True → silent no-op (return)."""
        gw = _StubGateway()
        tools = ToolsSpec(allow_all_tools=True)
        policy = type("P", (), {"tools": tools})()
        # Не должно бросить.
        gw._enforce_tool_policy_once(_make_request(), policy)

    def test_no_policy_allows(self) -> None:
        """policy=None → no-op (default policy)."""
        gw = _StubGateway()
        # Не должно бросить.
        gw._enforce_tool_policy_once(_make_request(), None)

    def test_policy_without_tools_allows(self) -> None:
        """policy.tools is None → no-op (policy без tools section)."""
        gw = _StubGateway()
        policy = type("P", (), {})()
        # Не должно бросить.
        gw._enforce_tool_policy_once(_make_request(), policy)

    def test_nonempty_whitelist_passes(self) -> None:
        """Non-empty whitelist → доходит до enforce (tool может пройти/упасть)."""
        gw = _StubGateway()
        tools = ToolsSpec(whitelist=["db.read.*"])
        policy = type("P", (), {"tools": tools})()
        # tool_name == workflow_id (default fallback), workflow_id="wf-1".
        # "wf-1" не в whitelist ["db.read.*"] → должно raise.
        with pytest.raises(ToolPolicyViolationError, match="wf-1"):
            gw._enforce_tool_policy_once(_make_request(), policy)