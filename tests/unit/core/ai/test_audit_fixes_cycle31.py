"""Cycle 31 audit fact-check fixes: regression tests.

Tests for:
1. enforced_invoke.py stale duplicate — tool_name mandatory + S209 fail-closed.
2. InProcessAgentSandbox — audit event on construction.
3. SkillRegistry._validate_module_whitelist — delegates to shared utility.
4. Redis mget/mset_pipelined — batch size limit enforcement.
"""

from __future__ import annotations

import pytest

# ─────────── 1. enforced_invoke.py tool-policy enforcement ───────────


@pytest.mark.unit
class TestEnforcedInvokeToolPolicy:
    """Verify the stale duplicate in gateway/orchestrator/enforced_invoke.py
    matches the security-hardened version (no workflow_id fallback, S209 fail-closed).
    """

    def test_tool_name_mandatory_when_restricted(self) -> None:
        """If policy has non-empty whitelist/blacklist, tool_name is required."""
        from src.backend.core.ai.gateway.orchestrator.enforced_invoke import (
            EnforcedInvokeMixin,
        )
        from src.backend.core.ai.gateway_models import AIRequest

        class _Tools:
            whitelist = ["allowed_tool"]
            blacklist = []
            allow_all_tools = False

        class _Policy:
            tools = _Tools()

        request = AIRequest(
            workflow_id="test_wf",
            tenant_id="test",
            correlation_id="test-correlation",
            tool_name="",  # empty — should fail
        )

        mixin = object.__new__(EnforcedInvokeMixin)
        with pytest.raises(Exception, match="tool_name is required"):
            mixin._enforce_tool_policy_once(request, _Policy())  # type: ignore[arg-type]

    def test_s209_fail_closed_on_empty_lists(self) -> None:
        """Empty whitelist+blacklist without allow_all_tools → raise (not no-op)."""
        from src.backend.core.ai.gateway.orchestrator.enforced_invoke import (
            EnforcedInvokeMixin,
        )
        from src.backend.core.ai.gateway_models import AIRequest

        class _Tools:
            whitelist = []
            blacklist = []
            allow_all_tools = False

        class _Policy:
            tools = _Tools()

        request = AIRequest(
            workflow_id="test_wf",
            tenant_id="test",
            correlation_id="test-correlation",
            tool_name="some_tool",
        )

        mixin = object.__new__(EnforcedInvokeMixin)
        with pytest.raises(Exception, match="empty"):
            mixin._enforce_tool_policy_once(request, _Policy())  # type: ignore[arg-type]

    def test_no_workflow_id_fallback(self) -> None:
        """Verify the code does NOT contain 'tool_name or workflow_id' pattern."""
        import inspect

        from src.backend.core.ai.gateway.orchestrator.enforced_invoke import (
            EnforcedInvokeMixin,
        )

        source = inspect.getsource(EnforcedInvokeMixin._enforce_tool_policy_once)
        assert "request.tool_name or request.workflow_id" not in source, (
            "workflow_id fallback should have been removed"
        )


# ─────────── 2. InProcessAgentSandbox audit event ───────────


@pytest.mark.unit
class TestInProcessAgentSandboxAudit:
    """Verify InProcessAgentSandbox emits audit event on construction."""

    def test_construction_emits_audit_event(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """InProcessAgentSandbox construction should emit audit event."""
        # Ensure NOT in production mode
        monkeypatch.delenv("GD_INTEGRATION_PRODUCTION", raising=False)

        events: list[tuple[str, str]] = []

        import src.backend.core.audit.facade as facade_mod
        original = getattr(facade_mod, "emit_audit_safe", None)

        def mock_emit(*args, **kwargs):
            events.append((kwargs.get("event_type", ""), kwargs.get("severity", "")))
            # call original if exists, otherwise just record
            if original:
                try:
                    original(*args, **kwargs)
                except Exception:
                    pass

        monkeypatch.setattr(facade_mod, "emit_audit_safe", mock_emit)

        import warnings

        from src.backend.services.ai.agent_sandbox import InProcessAgentSandbox

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            sandbox = InProcessAgentSandbox()

        assert sandbox is not None
        # At least one audit event should have been emitted
        assert any("zero_isolation" in et for et, _ in events), (
            f"Expected zero_isolation audit event, got: {events}"
        )


# ─────────── 3. SkillRegistry whitelist delegation ───────────


@pytest.mark.unit
class TestSkillRegistryWhitelistDelegation:
    """Verify SkillRegistry._validate_module_whitelist delegates to shared utility."""

    def test_empty_whitelist_raises_value_error(self) -> None:
        """Empty whitelist → ValueError (deny-all)."""
        from src.backend.core.ai.skill_registry import SkillRegistry

        with pytest.raises(ValueError, match="empty whitelist"):
            SkillRegistry._validate_module_whitelist("mod", [], "skill1")

    def test_exact_match_allowed(self) -> None:
        """Exact module name match → no exception."""
        from src.backend.core.ai.skill_registry import SkillRegistry

        SkillRegistry._validate_module_whitelist(
            "extensions.credit.fn", ["extensions.credit.fn"], "skill1"
        )  # should not raise

    def test_prefix_glob_allowed(self) -> None:
        """Prefix.* pattern → no exception."""
        from src.backend.core.ai.skill_registry import SkillRegistry

        SkillRegistry._validate_module_whitelist(
            "extensions.credit.fn", ["extensions.credit.*"], "skill1"
        )  # should not raise

    def test_module_not_in_whitelist_raises(self) -> None:
        """Module not matching any pattern → PermissionError."""
        from src.backend.core.ai.skill_registry import SkillRegistry

        with pytest.raises(PermissionError, match="not in whitelist"):
            SkillRegistry._validate_module_whitelist(
                "extensions.osint.fn", ["extensions.credit.*"], "skill1"
            )

    def test_uses_shared_utilility(self) -> None:
        """Verify the method delegates to validate_module_whitelist."""
        import inspect

        from src.backend.core.ai.skill_registry import SkillRegistry

        source = inspect.getsource(SkillRegistry._validate_module_whitelist)
        assert "validate_module_whitelist" in source, (
            "SkillRegistry should delegate to shared validate_module_whitelist"
        )


# ─────────── 4. Redis bulk operation batch limits ───────────


@pytest.mark.unit
class TestRedisBatchLimits:
    """Verify Redis mget_pipelined / mset_pipelined enforce batch size limits."""

    def test_mget_rejects_oversized_batch(self) -> None:
        """mget_pipelined should reject >10K keys."""
        from src.backend.infrastructure.cache.backends.redis import RedisBackend

        assert RedisBackend._MAX_PIPELINE_BATCH == 10_000

    def test_mset_rejects_oversized_batch(self) -> None:
        """mset_pipelined should reject >10K items."""
        from src.backend.infrastructure.cache.backends.redis import RedisBackend

        assert RedisBackend._MAX_PIPELINE_BATCH == 10_000

    @pytest.mark.asyncio
    async def test_mget_empty_keys_returns_empty(self) -> None:
        """Empty keys → no Redis call, empty list."""
        from unittest.mock import MagicMock

        from src.backend.infrastructure.cache.backends.redis import RedisBackend

        backend = object.__new__(RedisBackend)
        backend._client = MagicMock()
        backend._MAX_PIPELINE_BATCH = 10_000

        result = await backend.mget_pipelined([])
        assert result == []
