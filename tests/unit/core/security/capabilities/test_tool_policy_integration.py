"""S79 W4 — tests для check_tool_with_policy + filter_tools_with_gate
(FINAL_REPORT_V2 направление #4 closure: CapabilityGate + AIPolicySpec.tools
two-layer enforcement)."""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from src.backend.core.ai.policy.spec import ToolsSpec
from src.backend.core.ai.policy.enforcer.tools_policy import (
    ToolPolicyViolationError,
)
from src.backend.core.security.capabilities.errors import (
    CapabilityDeniedError,
)
from src.backend.core.security.capabilities.tool_policy_integration import (
    check_tool_with_policy,
    filter_tools_with_gate,
    ToolCapabilityCheckError,
)


# Mock gate helper
# ============================================================================


class MockGate:
    """Mock CapabilityGate с controlled allowlist."""

    def __init__(self, allowed: list[str]) -> None:
        self._allowed = set(allowed)
        self.check_calls: list[tuple[str, str, Any]] = []

    def check(self, plugin: str, tool: str, scope: str | None) -> None:
        self.check_calls.append((plugin, tool, scope))
        if tool not in self._allowed:
            raise CapabilityDeniedError(
                plugin=plugin,
                capability=tool,
                requested_scope=scope,
                declared_scope=None,
            )


# check_tool_with_policy tests
# ============================================================================


def test_check_passes_both_layers() -> None:
    """Tool allowed: capability + whitelist match → no error."""
    gate = MockGate(allowed=["db.read", "ai.invoke"])
    policy = ToolsSpec(whitelist=["db.read", "ai.invoke"], on_violation="fail")
    check_tool_with_policy(
        gate=gate, plugin="test", tool_name="db.read",
        scope=None, policy=policy,
    )
    # Verify gate.check was called
    assert gate.check_calls == [("test", "db.read", None)]


def test_check_denied_by_capability() -> None:
    """Tool not declared → CapabilityDeniedError raised."""
    gate = MockGate(allowed=["db.read"])
    policy = ToolsSpec(on_violation="fail")
    with pytest.raises(CapabilityDeniedError, match="Capability denied"):
        check_tool_with_policy(
            gate=gate, plugin="test", tool_name="fs.write",
            scope=None, policy=policy,
        )


def test_check_denied_by_whitelist() -> None:
    """Tool declared but not in whitelist → ToolPolicyViolationError."""
    gate = MockGate(allowed=["ai.invoke"])
    policy = ToolsSpec(whitelist=["db.read"], on_violation="fail")
    with pytest.raises(ToolPolicyViolationError, match="violates AIPolicySpec"):
        check_tool_with_policy(
            gate=gate, plugin="test", tool_name="ai.invoke",
            scope=None, policy=policy,
        )


def test_check_denied_by_blacklist() -> None:
    """Tool declared AND in blacklist → ToolPolicyViolationError (blacklist wins)."""
    gate = MockGate(allowed=["fs.write"])
    policy = ToolsSpec(blacklist=["fs.write"], on_violation="fail")
    with pytest.raises(ToolPolicyViolationError, match="violates AIPolicySpec"):
        check_tool_with_policy(
            gate=gate, plugin="test", tool_name="fs.write",
            scope=None, policy=policy,
        )


def test_check_capability_checked_first() -> None:
    """CapabilityGate check happens BEFORE AIPolicySpec.tools check."""
    # Tool not declared AND not in whitelist — should fail on capability (first).
    gate = MockGate(allowed=[])  # Nothing allowed
    policy = ToolsSpec(whitelist=["unknown"], on_violation="fail")
    with pytest.raises(CapabilityDeniedError):
        check_tool_with_policy(
            gate=gate, plugin="test", tool_name="unknown",
            scope=None, policy=policy,
        )


# filter_tools_with_gate tests
# ============================================================================


def test_filter_passes_all() -> None:
    """All tools pass both layers → returned as-is (order preserved)."""
    gate = MockGate(allowed=["db.read", "ai.invoke", "net.call"])
    policy = ToolsSpec(whitelist=["db.read", "ai.invoke", "net.call"])
    filtered = filter_tools_with_gate(
        gate=gate, plugin="test",
        tool_names=["db.read", "ai.invoke", "net.call"],
        scope=None, policy=policy,
    )
    assert filtered == ["db.read", "ai.invoke", "net.call"]


def test_filter_drops_undeclared_capability() -> None:
    """Tools not declared in gate → dropped."""
    gate = MockGate(allowed=["db.read"])  # Only db.read allowed
    policy = ToolsSpec()  # No whitelist restriction
    filtered = filter_tools_with_gate(
        gate=gate, plugin="test",
        tool_names=["db.read", "fs.write", "shell.execute"],
        scope=None, policy=policy,
    )
    assert filtered == ["db.read"]


def test_filter_drops_white_list_violation() -> None:
    """Tools not in AIPolicySpec.tools whitelist → dropped."""
    gate = MockGate(allowed=["db.read", "ai.invoke", "fs.write"])
    policy = ToolsSpec(whitelist=["db.read", "ai.invoke"])
    filtered = filter_tools_with_gate(
        gate=gate, plugin="test",
        tool_names=["db.read", "ai.invoke", "fs.write"],
        scope=None, policy=policy,
    )
    assert filtered == ["db.read", "ai.invoke"]


def test_filter_drops_blacklist() -> None:
    """Tools in blacklist → dropped (blacklist precedence)."""
    gate = MockGate(allowed=["db.read", "ai.invoke"])
    policy = ToolsSpec(blacklist=["ai.invoke"])
    filtered = filter_tools_with_gate(
        gate=gate, plugin="test",
        tool_names=["db.read", "ai.invoke"],
        scope=None, policy=policy,
    )
    assert filtered == ["db.read"]


def test_filter_drops_both_layers() -> None:
    """Mixed: some pass, some fail capability, some fail whitelist."""
    gate = MockGate(allowed=["db.read", "ai.invoke", "fs.write"])
    policy = ToolsSpec(whitelist=["db.read", "ai.invoke"])
    filtered = filter_tools_with_gate(
        gate=gate, plugin="test",
        tool_names=[
            "db.read",  # OK (cap + whitelist)
            "ai.invoke",  # OK (cap + whitelist)
            "fs.write",  # OK (cap) but NOT in whitelist
            "shell.execute",  # NOT in cap, NOT in whitelist
        ],
        scope=None, policy=policy,
    )
    assert filtered == ["db.read", "ai.invoke"]


def test_filter_preserves_order() -> None:
    """Filter preserves input order."""
    gate = MockGate(allowed=["z", "a", "m", "b"])
    policy = ToolsSpec()  # No restriction
    filtered = filter_tools_with_gate(
        gate=gate, plugin="test",
        tool_names=["z", "a", "m", "b"],
        scope=None, policy=policy,
    )
    assert filtered == ["z", "a", "m", "b"]


def test_filter_empty_input() -> None:
    """Empty tool list → empty result."""
    gate = MockGate(allowed=["anything"])
    policy = ToolsSpec()
    filtered = filter_tools_with_gate(
        gate=gate, plugin="test", tool_names=[],
        scope=None, policy=policy,
    )
    assert filtered == []


def test_filter_with_iterator_input() -> None:
    """Accepts iterable (not just list) per signature."""
    gate = MockGate(allowed=["db.read"])
    policy = ToolsSpec()
    filtered = filter_tools_with_gate(
        gate=gate, plugin="test",
        tool_names=iter(["db.read", "fs.write"]),
        scope=None, policy=policy,
    )
    assert filtered == ["db.read"]


def test_filter_scope_passed_to_gate() -> None:
    """Scope argument forwarded to gate.check()."""
    gate = MockGate(allowed=["db.read"])
    policy = ToolsSpec()
    filter_tools_with_gate(
        gate=gate, plugin="test",
        tool_names=["db.read"],
        scope="tenant_abc",
        policy=policy,
    )
    assert gate.check_calls == [("test", "db.read", "tenant_abc")]


# ToolCapabilityCheckError tests
# ============================================================================


def test_tool_capability_check_error_inherits_permission_error() -> None:
    """ToolCapabilityCheckError — PermissionError subclass."""
    assert issubclass(ToolCapabilityCheckError, PermissionError)


def test_tool_capability_check_error_constructable() -> None:
    """ToolCapabilityCheckError can be raised and caught."""
    with pytest.raises(ToolCapabilityCheckError, match="test"):
        raise ToolCapabilityCheckError("test error")
