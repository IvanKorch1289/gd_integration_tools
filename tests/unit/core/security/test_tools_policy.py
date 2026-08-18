"""Coverage tests для tools_policy (Sprint 5, 2026-08-17).

TDD: тесты для edge cases AIPolicySpec.tools enforcement.
Реальный код в src/backend/core/ai/policy/enforcer/tools_policy.py.

Coverage targets:
- check_tool_allowed: whitelist glob, blacklist glob, both empty,
  whitelist+blacklist interaction
- enforce_tool_policy: fail/warn/block modes
- ToolPolicyViolationError: PermissionError subclass + message format
"""

from __future__ import annotations

import pytest

from src.backend.core.ai.policy.enforcer.tools_policy import (
    ToolPolicyViolationError,
    check_tool_allowed,
    enforce_tool_policy,
)
from src.backend.core.ai.policy.spec import ToolsSpec


class TestToolPolicyViolationError:
    """ToolPolicyViolationError — exception contract."""

    def test_is_permission_error_subclass(self) -> None:
        """ToolPolicyViolationError MUST be subclass of PermissionError.

        Authorization ошибки должны ловиться стандартным
        except PermissionError handler'ом в FastAPI middleware."""
        assert issubclass(ToolPolicyViolationError, PermissionError)

    def test_str_contains_message(self) -> None:
        exc = ToolPolicyViolationError("forbidden tool")
        assert "forbidden tool" in str(exc)


class TestCheckToolAllowed:
    """check_tool_allowed — pure function (no side effects)."""

    def test_empty_spec_allows_all(self) -> None:
        """Backward compat: pre-S76 YAML без tools секции → allow all.

        Это документированное поведение (см. docstring tools_policy.py:23).
        """
        spec = ToolsSpec(whitelist=[], blacklist=[])
        assert check_tool_allowed("any.tool.name", spec) is True

    def test_whitelist_exact_match(self) -> None:
        spec = ToolsSpec(whitelist=["db.read"], blacklist=[])
        assert check_tool_allowed("db.read", spec) is True

    def test_whitelist_no_match(self) -> None:
        spec = ToolsSpec(whitelist=["db.read"], blacklist=[])
        assert check_tool_allowed("fs.write", spec) is False

    def test_whitelist_glob_match(self) -> None:
        spec = ToolsSpec(whitelist=["db.*"], blacklist=[])
        assert check_tool_allowed("db.read", spec) is True
        assert check_tool_allowed("db.write", spec) is True

    def test_whitelist_glob_no_match(self) -> None:
        spec = ToolsSpec(whitelist=["db.*"], blacklist=[])
        assert check_tool_allowed("fs.write", spec) is False

    def test_whitelist_glob_partial_no_match(self) -> None:
        """``db.*`` must NOT match ``dbapi`` (no dot prefix).

        Glob без ``.`` suffix — паттерн ``db.*`` = ``db.`` prefix."""
        spec = ToolsSpec(whitelist=["db.*"], blacklist=[])
        # ``dbapi.read`` не должен пройти (нет ``db.`` prefix)
        assert check_tool_allowed("dbapi.read", spec) is False

    def test_blacklist_match_blocks(self) -> None:
        """Blacklist applied regardless of whitelist contents."""
        spec = ToolsSpec(whitelist=[], blacklist=["fs.write"])
        assert check_tool_allowed("fs.write", spec) is False

    def test_blacklist_glob_match(self) -> None:
        spec = ToolsSpec(whitelist=[], blacklist=["fs.*"])
        assert check_tool_allowed("fs.write", spec) is False
        assert check_tool_allowed("fs.delete", spec) is False
        assert check_tool_allowed("db.read", spec) is True

    def test_blacklist_priority_over_whitelist(self) -> None:
        """Если tool в обоих списках — blacklist побеждает (deny > allow)."""
        spec = ToolsSpec(whitelist=["*"], blacklist=["fs.write"])
        assert check_tool_allowed("fs.write", spec) is False
        assert check_tool_allowed("db.read", spec) is True

    def test_case_sensitive_glob(self) -> None:
        """Glob case-sensitive (consistent with core/ai/policy/resolver.py:220)."""
        spec = ToolsSpec(whitelist=["DB.*"], blacklist=[])
        assert check_tool_allowed("DB.read", spec) is True
        assert check_tool_allowed("db.read", spec) is False


class TestEnforceToolPolicy:
    """enforce_tool_policy — side-effecting wrapper."""

    def test_allowed_tool_passes(self) -> None:
        spec = ToolsSpec(whitelist=["db.*"], blacklist=[])
        # Should NOT raise
        enforce_tool_policy("db.read", spec)

    def test_blocked_tool_raises_fail_mode(self) -> None:
        spec = ToolsSpec(
            whitelist=[],
            blacklist=["fs.write"],
            on_violation="fail",
        )
        with pytest.raises(ToolPolicyViolationError, match="fs.write"):
            enforce_tool_policy("fs.write", spec)

    def test_empty_spec_does_not_raise(self) -> None:
        """Empty whitelist + empty blacklist = no restriction (allow all)."""
        spec = ToolsSpec(whitelist=[], blacklist=[], on_violation="fail")
        enforce_tool_policy("any.tool", spec)

    def test_failure_message_includes_spec_state(self) -> None:
        spec = ToolsSpec(
            whitelist=[],
            blacklist=["danger.*"],
            on_violation="fail",
        )
        with pytest.raises(ToolPolicyViolationError) as exc_info:
            enforce_tool_policy("danger.exec", spec)
        msg = str(exc_info.value)
        # Message должен включать whitelist+blacklist для debug
        assert "Whitelist" in msg or "whitelist" in msg
        assert "Blacklist" in msg or "blacklist" in msg


class TestFilterToolsByPolicy:
    """filter_tools_by_policy — bulk filter helper."""

    def test_filters_disallowed(self) -> None:
        spec = ToolsSpec(whitelist=["db.*"], blacklist=[])
        from src.backend.core.ai.policy.enforcer.tools_policy import (
            filter_tools_by_policy,
        )
        result = filter_tools_by_policy(
            ["db.read", "db.write", "fs.delete"],
            spec,
        )
        assert "db.read" in result
        assert "db.write" in result
        assert "fs.delete" not in result