"""S76 W4 — tests для ToolsSpec whitelist/blacklist (FINAL_REPORT_V2 P0-B closure)."""

from __future__ import annotations

import pytest

from src.backend.core.ai.policy.enforcer import AIPolicyEnforcer
from src.backend.core.ai.policy.enforcer.tools_policy import (
    ToolPolicyViolationError,
    check_tool_allowed,
    enforce_tool_policy,
    filter_tools_by_policy,
)
from src.backend.core.ai.policy.spec import AIPolicySpec, ModelRouterSpec, ToolsSpec

# ToolsSpec data model tests
# ============================================================================


def test_tools_spec_default_empty() -> None:
    """Default ToolsSpec: пустые whitelist/blacklist, on_violation='fail'."""
    spec = ToolsSpec()
    assert spec.whitelist == []
    assert spec.blacklist == []
    assert spec.on_violation == "fail"


def test_tools_spec_with_whitelist() -> None:
    """Whitelist configuration."""
    spec = ToolsSpec(
        whitelist=["db.read.orders", "ai.invoke.credit_check"], on_violation="warn"
    )
    assert len(spec.whitelist) == 2
    assert spec.on_violation == "warn"


def test_tools_spec_with_blacklist() -> None:
    """Blacklist configuration."""
    spec = ToolsSpec(blacklist=["fs.write", "shell.execute"], on_violation="block")
    assert len(spec.blacklist) == 2
    assert spec.on_violation == "block"


def test_aipolicyspec_tools_field_default() -> None:
    """AIPolicySpec.tools default = empty ToolsSpec (backward-compat)."""
    spec = AIPolicySpec(
        name="test",
        workflow_pattern="test_*",
        model_router=ModelRouterSpec(primary="openai/gpt-4"),
    )
    assert isinstance(spec.tools, ToolsSpec)
    assert spec.tools.whitelist == []
    assert spec.tools.blacklist == []


# check_tool_allowed tests
# ============================================================================


def test_check_tool_allowed_default_allows_all() -> None:
    """Default ToolsSpec (no whitelist, no blacklist) allows all tools."""
    spec = ToolsSpec()
    assert check_tool_allowed("anything", spec) is True
    assert check_tool_allowed("fs.write", spec) is True
    assert check_tool_allowed("db.read", spec) is True


def test_check_tool_allowed_whitelist_match() -> None:
    """Whitelist match → allowed."""
    spec = ToolsSpec(whitelist=["db.read", "ai.invoke"])
    assert check_tool_allowed("db.read", spec) is True
    assert check_tool_allowed("ai.invoke", spec) is True


def test_check_tool_allowed_whitelist_miss() -> None:
    """Whitelist miss → not allowed."""
    spec = ToolsSpec(whitelist=["db.read", "ai.invoke"])
    assert check_tool_allowed("fs.write", spec) is False
    assert check_tool_allowed("network", spec) is False


def test_check_tool_allowed_blacklist_match() -> None:
    """Blacklist match → not allowed."""
    spec = ToolsSpec(blacklist=["fs.write", "shell.execute"])
    assert check_tool_allowed("fs.write", spec) is False
    assert check_tool_allowed("shell.execute", spec) is False


def test_check_tool_allowed_blacklist_miss() -> None:
    """Blacklist miss → allowed (если whitelist пуст)."""
    spec = ToolsSpec(blacklist=["fs.write"])
    assert check_tool_allowed("db.read", spec) is True
    assert check_tool_allowed("ai.invoke", spec) is True


def test_check_tool_allowed_blacklist_wins_over_whitelist() -> None:
    """Blacklist precedence над whitelist (security: deny takes priority)."""
    spec = ToolsSpec(whitelist=["db.read", "fs.write"], blacklist=["fs.write"])
    # fs.write в whitelist, но также в blacklist → blacklist wins
    assert check_tool_allowed("fs.write", spec) is False
    assert check_tool_allowed("db.read", spec) is True


# enforce_tool_policy tests
# ============================================================================


def test_enforce_tool_policy_fail_default() -> None:
    """on_violation='fail' (default) → raise ToolPolicyViolationError."""
    spec = ToolsSpec(whitelist=["db.read"], on_violation="fail")
    with pytest.raises(ToolPolicyViolationError, match="violates AIPolicySpec"):
        enforce_tool_policy("fs.write", spec)


def test_enforce_tool_policy_warn(caplog: pytest.LogCaptureFixture) -> None:
    """on_violation='warn' → log warning, allow invocation."""
    import logging

    caplog.set_level(logging.WARNING)
    spec = ToolsSpec(whitelist=["db.read"], on_violation="warn")
    # No exception raised
    enforce_tool_policy("fs.write", spec)
    # Warning logged
    assert any("violates policy" in rec.message for rec in caplog.records)


def test_enforce_tool_policy_block() -> None:
    """on_violation='block' → raise (silent, no log) per spec."""
    spec = ToolsSpec(whitelist=["db.read"], on_violation="block")
    with pytest.raises(ToolPolicyViolationError, match="blocked per policy"):
        enforce_tool_policy("fs.write", spec)


def test_enforce_tool_policy_allowed_no_action() -> None:
    """Allowed tool → no exception, no log, no side effect."""
    spec = ToolsSpec(whitelist=["db.read", "ai.invoke"], blacklist=["fs.write"])
    # Allowed tools не raise
    enforce_tool_policy("db.read", spec)
    enforce_tool_policy("ai.invoke", spec)
    # Blacklisted tool raises
    with pytest.raises(ToolPolicyViolationError):
        enforce_tool_policy("fs.write", spec)


def test_enforce_tool_policy_unknown_mode_defaults_to_fail() -> None:
    """Unknown on_violation mode → defensive fail (safe default)."""
    # Bypass Pydantic validation (direct attr set)
    spec = ToolsSpec(whitelist=["db.read"])
    object.__setattr__(spec, "on_violation", "unknown_mode")
    with pytest.raises(ToolPolicyViolationError, match="unknown on_violation"):
        enforce_tool_policy("fs.write", spec)


# filter_tools_by_policy tests
# ============================================================================


def test_filter_tools_empty_spec_passes_all() -> None:
    """Empty spec → all tools pass (no restriction)."""
    tools = ["db.read", "fs.write", "ai.invoke"]
    filtered = filter_tools_by_policy(tools, ToolsSpec())
    assert filtered == tools


def test_filter_tools_whitelist_removes_non_whitelisted() -> None:
    """Whitelist filter removes non-whitelisted tools."""
    tools = ["db.read", "fs.write", "ai.invoke", "network"]
    spec = ToolsSpec(whitelist=["db.read", "ai.invoke"])
    filtered = filter_tools_by_policy(tools, spec)
    assert filtered == ["db.read", "ai.invoke"]


def test_filter_tools_blacklist_removes_blacklisted() -> None:
    """Blacklist filter removes blacklisted tools."""
    tools = ["db.read", "fs.write", "ai.invoke"]
    spec = ToolsSpec(blacklist=["fs.write"])
    filtered = filter_tools_by_policy(tools, spec)
    assert filtered == ["db.read", "ai.invoke"]


def test_filter_tools_preserves_order() -> None:
    """Filter preserves input order."""
    tools = ["z_tool", "a_tool", "m_tool", "b_tool"]
    spec = ToolsSpec(blacklist=["m_tool"])
    filtered = filter_tools_by_policy(tools, spec)
    assert filtered == ["z_tool", "a_tool", "b_tool"]


def test_filter_tools_with_iterator_input() -> None:
    """Accepts iterable (not just list) per signature."""
    spec = ToolsSpec(whitelist=["db.read"])
    filtered = filter_tools_by_policy(iter(["db.read", "fs.write"]), spec)
    assert filtered == ["db.read"]


# AIPolicyEnforcer.filter_tools integration tests
# ============================================================================


def test_aipolicy_enforcer_filter_tools() -> None:
    """AIPolicyEnforcer.filter_tools работает как convenience wrapper."""
    enforcer = AIPolicyEnforcer()
    tools = ["db.read.orders", "fs.write", "shell.execute", "ai.invoke.credit_check"]
    spec = ToolsSpec(blacklist=["fs.write", "shell.execute"])
    filtered = enforcer.filter_tools(tools, spec)
    assert "fs.write" not in filtered
    assert "shell.execute" not in filtered
    assert "db.read.orders" in filtered
    assert "ai.invoke.credit_check" in filtered
