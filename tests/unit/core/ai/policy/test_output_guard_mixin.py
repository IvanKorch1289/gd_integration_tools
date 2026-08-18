"""Coverage tests для output_guard_mixin (Sprint 222, 2026-08-17).

TDD: tests для core/ai/policy/enforcer/output_guard_mixin.py.

output_guard_mixin.py coverage baseline: 82% (per Sprint 221).
Target: 95%+ via these tests.

Coverage targets:
- guard_output: empty guards, empty content, normal flow
- _guard_output_one: unknown engine, runtime not configured,
  runtime without classify, classify exception (fail + warn),
  unsafe content (block), safe content (pass)
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.backend.core.ai.errors import GuardrailViolationError
from src.backend.core.ai.gateway_models import AIRequest, AIResponse
from src.backend.core.ai.policy.enforcer.output_guard_mixin import OutputGuardMixin
from src.backend.core.ai.policy.spec import GuardRef


def _make_response(content: str = "test response") -> AIResponse:
    return AIResponse(
        content=content,
        model_used="test-model",
    )


def _make_policy(guards: list[GuardRef] | None = None) -> MagicMock:
    p = MagicMock()
    p.output_guards = guards or []
    return p


class _StubEnforcer(OutputGuardMixin):
    """Minimal subclass to test mixin methods in isolation."""

    def __init__(self) -> None:
        self._llama_guard_runtime: MagicMock | None = None
        self._handle_guard_block = AsyncMock()


@pytest.fixture
def enforcer() -> _StubEnforcer:
    return _StubEnforcer()


class TestGuardOutputEmpty:
    """Edge cases: no guards, empty content."""

    @pytest.mark.asyncio
    async def test_no_guards_returns_empty_list(self, enforcer: _StubEnforcer) -> None:
        response = _make_response("some content")
        policy = _make_policy(guards=[])

        result = await enforcer.guard_output(response, policy)
        assert result == []

    @pytest.mark.asyncio
    async def test_empty_content_returns_empty_list(
        self, enforcer: _StubEnforcer,
    ) -> None:
        response = _make_response("")
        policy = _make_policy(guards=[GuardRef(name="llama_guard:safe_v3", on_block="fail")])

        result = await enforcer.guard_output(response, policy)
        assert result == []


class TestGuardOutputNormal:
    """Normal guard flow."""

    @pytest.mark.asyncio
    async def test_safe_content_returns_passed_verdict(
        self, enforcer: _StubEnforcer,
    ) -> None:
        """LlamaGuard классифицирует content как safe → passed verdict."""
        # Mock runtime with classify that returns safe
        mock_result = MagicMock()
        mock_result.safe = True
        mock_result.flagged_categories = []
        mock_classify = AsyncMock(return_value=mock_result)
        mock_runtime = MagicMock()
        mock_runtime.classify = mock_classify
        enforcer._llama_guard_runtime = mock_runtime

        response = _make_response("safe content")
        policy = _make_policy(guards=[GuardRef(name="llama_guard:safe_v3", on_block="fail")])

        result = await enforcer.guard_output(response, policy)

        assert len(result) == 1
        assert result[0].verdict == "passed"
        assert result[0].categories == []
        assert result[0].guard_name == "llama_guard:safe_v3"

    @pytest.mark.asyncio
    async def test_unsafe_content_returns_blocked_verdict(
        self, enforcer: _StubEnforcer,
    ) -> None:
        """LlamaGuard классифицирует как unsafe → blocked verdict + handle_block called."""
        mock_result = MagicMock()
        mock_result.safe = False
        mock_result.flagged_categories = ["violence"]
        mock_classify = AsyncMock(return_value=mock_result)
        mock_runtime = MagicMock()
        mock_runtime.classify = mock_classify
        enforcer._llama_guard_runtime = mock_runtime

        response = _make_response("unsafe content")
        policy = _make_policy(guards=[GuardRef(name="llama_guard:safe_v3", on_block="fail")])

        result = await enforcer.guard_output(response, policy)

        assert len(result) == 1
        assert result[0].verdict == "blocked"
        assert "violence" in result[0].categories
        # Production code calls _handle_guard_block without await (potential issue)
        enforcer._handle_guard_block.assert_called_once_with(
            guard_name="llama_guard:safe_v3",
            flagged=["violence"],
            on_block="fail",
            content="unsafe content",
        )


class TestGuardOutputOneEngineDispatch:
    """_guard_output_one — engine dispatch."""

    @pytest.mark.asyncio
    async def test_unknown_engine_returns_none_skipped(
        self, enforcer: _StubEnforcer,
    ) -> None:
        response = _make_response()
        ref = GuardRef(name="unknown:engine", on_block="fail")

        result = await enforcer._guard_output_one(response, ref)
        # Unknown engine → skip (None)
        assert result is None

    @pytest.mark.asyncio
    async def test_no_runtime_returns_none_skipped(
        self, enforcer: _StubEnforcer,
    ) -> None:
        response = _make_response()
        ref = GuardRef(name="llama_guard:safe_v3", on_block="fail")
        enforcer._llama_guard_runtime = None

        result = await enforcer._guard_output_one(response, ref)
        # Runtime not configured → skip
        assert result is None

    @pytest.mark.asyncio
    async def test_runtime_without_classify_method_returns_none(
        self, enforcer: _StubEnforcer,
    ) -> None:
        response = _make_response()
        ref = GuardRef(name="llama_guard:safe_v3", on_block="fail")
        # Runtime без classify method
        mock_runtime = MagicMock(spec=[])  # no attributes
        enforcer._llama_guard_runtime = mock_runtime

        result = await enforcer._guard_output_one(response, ref)
        assert result is None


class TestGuardOutputOneException:
    """classify exception — fail-closed or warn depending on on_block."""

    @pytest.mark.asyncio
    async def test_classify_exception_on_block_fail_raises(
        self, enforcer: _StubEnforcer,
    ) -> None:
        """Если classify throws + on_block=fail → GuardrailViolationError."""
        mock_classify = AsyncMock(side_effect=RuntimeError("LlamaGuard down"))
        mock_runtime = MagicMock()
        mock_runtime.classify = mock_classify
        enforcer._llama_guard_runtime = mock_runtime

        response = _make_response("test content")
        ref = GuardRef(name="llama_guard:safe_v3", on_block="fail")

        with pytest.raises(GuardrailViolationError, match="llamaguard_error"):
            await enforcer._guard_output_one(response, ref)

    @pytest.mark.asyncio
    async def test_classify_exception_on_block_warn_returns_none(
        self, enforcer: _StubEnforcer,
    ) -> None:
        """Если classify throws + on_block=warn → log + return None (continue)."""
        mock_classify = AsyncMock(side_effect=RuntimeError("LlamaGuard down"))
        mock_runtime = MagicMock()
        mock_runtime.classify = mock_classify
        enforcer._llama_guard_runtime = mock_runtime

        response = _make_response("test content")
        ref = GuardRef(name="llama_guard:safe_v3", on_block="warn")

        result = await enforcer._guard_output_one(response, ref)
        # Warn mode → return None (skip and continue, no exception)
        assert result is None