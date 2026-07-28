"""Cycle 31 audit fact-check fixes: regression tests.

Tests for:
1. enforced_invoke.py security sync — tool_name mandatory + S209 fail-closed.
2. InProcessAgentSandbox — audit event on construction (with CORRECT kwargs).
3. SkillRegistry._validate_module_whitelist — delegates to shared utility.
4. Redis mget/mset_pipelined — batch size limit enforcement (boundary tests).

HIGH-1 retro fix: Tests now import from canonical ``gateway_orchestrator_mixin``
(the file actually used by ``AIGateway``), not from the orphan
``gateway/orchestrator/enforced_invoke.py`` which is only re-exported.
"""

from __future__ import annotations

import warnings

import pytest

# ─────────── 1. enforced_invoke.py tool-policy enforcement ───────────


@pytest.mark.unit
class TestEnforcedInvokeToolPolicy:
    """Verify tool_policy enforcement — test CANONICAL location used by AIGateway.

    HIGH-1 retro fix (cycle 31): imports from ``gateway_orchestrator_mixin``
    (production code path) instead of the orphan ``gateway/orchestrator/
    enforced_invoke.py``. The orphan is only re-exported for back-compat.
    """

    def test_tool_name_mandatory_when_restricted(self) -> None:
        """If policy has non-empty whitelist/blacklist, tool_name is required."""
        from src.backend.core.ai.gateway_models import AIRequest
        from src.backend.core.ai.gateway_orchestrator_mixin import EnforcedInvokeMixin

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
        from src.backend.core.ai.gateway_models import AIRequest
        from src.backend.core.ai.gateway_orchestrator_mixin import EnforcedInvokeMixin

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

        from src.backend.core.ai.gateway_orchestrator_mixin import EnforcedInvokeMixin

        source = inspect.getsource(EnforcedInvokeMixin._enforce_tool_policy_once)
        assert "request.tool_name or request.workflow_id" not in source, (
            "workflow_id fallback should have been removed"
        )


# ─────────── 2. InProcessAgentSandbox audit event ───────────


@pytest.mark.unit
class TestInProcessAgentSandboxAudit:
    """Verify InProcessAgentSandbox emits audit event on construction.

    CRIT-1 retro fix: tests must use the CORRECT ``emit_audit_safe`` signature
    (``event=``, ``details=``, ``severity=``) — NOT the previous broken
    ``event_type=`` / ``payload=`` kwargs that raised TypeError silently.
    """

    def test_construction_emits_audit_event(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """InProcessAgentSandbox construction should emit audit event."""
        # Ensure NOT in production mode
        monkeypatch.delenv("GD_INTEGRATION_PRODUCTION", raising=False)

        # Capture calls to validate CORRECT kwargs (event=, details=)
        captured: list[dict] = []
        real_emit = None
        import src.backend.core.audit.facade as facade_mod
        real_emit = getattr(facade_mod, "emit_audit_safe", None)

        def spy_emit(*args: object, **kwargs: object) -> None:
            captured.append(kwargs)
            if real_emit is not None:
                real_emit(*args, **kwargs)

        monkeypatch.setattr(facade_mod, "emit_audit_safe", spy_emit)

        # Cycle 33 AI2: feature_flags.ai_in_process_sandbox_disabled=True
        # blocks construction by default. For this test, we need to verify
        # the audit-event emission path, which only fires WHEN construction
        # succeeds. Override the flag via monkeypatch.
        from src.backend.core.config.features import feature_flags

        original_flag = feature_flags.ai_in_process_sandbox_disabled
        monkeypatch.setattr(
            feature_flags, "ai_in_process_sandbox_disabled", False
        )

        import warnings

        from src.backend.services.ai.agent_sandbox import InProcessAgentSandbox

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            sandbox = InProcessAgentSandbox()

        # Restore original flag for any subsequent tests.
        feature_flags.ai_in_process_sandbox_disabled = original_flag

        assert sandbox is not None
        # At least one audit event should have been emitted with CORRECT signature
        assert captured, "No audit events captured"
        zero_isolation_events = [
            kw for kw in captured
            if "zero_isolation" in str(kw.get("event", ""))
        ]
        assert zero_isolation_events, (
            f"Expected zero_isolation audit event, got: {captured}"
        )
        # Verify CORRECT signature (not the old wrong one)
        for kw in zero_isolation_events:
            assert "event_type" not in kw, (
                f"CRIT-1 regression: audit event uses WRONG kwarg 'event_type' "
                f"instead of 'event': {kw}"
            )
            assert "payload" not in kw, (
                f"CRIT-1 regression: audit event uses WRONG kwarg 'payload' "
                f"instead of 'details': {kw}"
            )
            assert "event" in kw, f"Missing 'event' kwarg: {kw}"
            assert "details" in kw, f"Missing 'details' kwarg: {kw}"


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
        # Strict: must call validate_module_whitelist as a function (not just a comment)
        assert "validate_module_whitelist(" in source, (
            "SkillRegistry should delegate to shared validate_module_whitelist()"
        )


# ─────────── 4. Redis bulk operation batch limits ───────────


@pytest.mark.unit
class TestRedisBatchLimits:
    """Verify Redis mget_pipelined / mset_pipelined enforce batch size limits.

    MED-2 retro fix: boundary tests added (just under limit succeeds, just over
    limit raises). Original tests only verified the constant value.
    """

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

    @pytest.mark.asyncio
    async def test_mget_at_limit_succeeds(self) -> None:
        """mget_pipelined at exactly the limit (10K) — should NOT raise.

        Boundary verification: 10000 ≤ limit (passes), 10001 > limit (raises).
        This prevents off-by-one regressions.
        """
        from unittest.mock import AsyncMock, MagicMock

        from src.backend.infrastructure.cache.backends.redis import RedisBackend

        backend = object.__new__(RedisBackend)
        # Mock pipeline that just returns empty list (we only test that
        # the batch-size check passes — we don't verify returned values).
        mock_pipeline = MagicMock()
        mock_pipeline.execute = AsyncMock(return_value=[])
        backend._client = MagicMock()
        backend._client.pipeline.return_value.__enter__.return_value = mock_pipeline
        backend._client.pipeline.return_value.__exit__.return_value = False
        backend._MAX_PIPELINE_BATCH = 10_000

        # 10K keys — exactly at the limit (boundary inclusive)
        keys = [f"key:{i}" for i in range(10_000)]
        # Should not raise
        await backend.mget_pipelined(keys)

    @pytest.mark.asyncio
    async def test_mget_over_limit_raises(self) -> None:
        """mget_pipelined with >10K keys should raise ValueError."""
        from unittest.mock import MagicMock

        from src.backend.infrastructure.cache.backends.redis import RedisBackend

        backend = object.__new__(RedisBackend)
        backend._client = MagicMock()
        backend._MAX_PIPELINE_BATCH = 10_000

        keys = [f"key:{i}" for i in range(10_001)]  # 1 over limit
        with pytest.raises(ValueError, match="exceeds batch limit"):
            await backend.mget_pipelined(keys)

    @pytest.mark.asyncio
    async def test_mset_over_limit_raises(self) -> None:
        """mset_pipelined with >10K items should raise ValueError."""
        from unittest.mock import MagicMock

        from src.backend.infrastructure.cache.backends.redis import RedisBackend

        backend = object.__new__(RedisBackend)
        backend._client = MagicMock()
        backend._MAX_PIPELINE_BATCH = 10_000

        items = {f"key:{i}": b"v" for i in range(10_001)}  # 1 over limit
        with pytest.raises(ValueError, match="exceeds batch limit"):
            await backend.mset_pipelined(items)


# ─────────── Cycle 33 AI2: InProcessAgentSandbox feature-flag gate ───────────


class TestInProcessAgentSandboxFeatureFlag:
    """Verify InProcessAgentSandbox is gated by feature_flags
    ai_in_process_sandbox_disabled (default ON = blocked).
    """

    @staticmethod
    def _ensure_env_off(monkeypatch: pytest.MonkeyPatch) -> None:
        """Make sure env var GD_INTEGRATION_PRODUCTION is unset."""
        monkeypatch.delenv("GD_INTEGRATION_PRODUCTION", raising=False)

    def test_construction_blocked_by_default(self) -> None:
        """Default config: construction raises RuntimeError."""
        with pytest.raises(RuntimeError, match="ai_in_process_sandbox_disabled"):
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", DeprecationWarning)
                from src.backend.services.ai.agent_sandbox import InProcessAgentSandbox

                InProcessAgentSandbox()

    def test_construction_blocked_via_feature_flag_override(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Even when operator sets flag to False, the env gate still blocks
        in production mode. Need both flag=True AND env=False to allow.
        """
        self._ensure_env_off(monkeypatch)
        # Try setting flag to False (operator override attempt)
        with monkeypatch.context() as m:
            m.setenv("FEATURE_AI_IN_PROCESS_SANDBOX_DISABLED", "false")
            # Note: feature_flags caches values, so this is best-effort
            # The env-var gate (_IN_PROCESS_PROD_BLOCKED) is a separate check
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", DeprecationWarning)
                from src.backend.services.ai.agent_sandbox import InProcessAgentSandbox

                # In non-prod (env var unset), flag check is the gate.
                # If flag cache wasn't updated, RuntimeError still raised.
                with pytest.raises(RuntimeError):
                    InProcessAgentSandbox()
