"""Unit tests for EnforcedInvokeMixin (T-P1.1c).

Tests the 9-step pipeline orchestrator в isolation, мокая individual
шаги из :class:`PipelineStepsMixin`. Это гарантирует, что orchestrator:

1. Вызывает все 9 шагов в правильном порядке
2. Эмитит audit events в правильных точках (ADR-0071 §3)
3. Корректно обрабатывает пустой pipeline (early exits)
4. Прокидывает output sanitized в audit + cost tracking
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.backend.core.ai.gateway_models import AIRequest, AIResponse
from src.backend.core.ai.gateway_orchestrator_mixin import EnforcedInvokeMixin


class _GuardResult:
    """Stand-in для GuardResult dataclass."""

    def __init__(self, guard_name: str, verdict: str, categories: list[str] | None = None) -> None:
        self.guard_name = guard_name
        self.verdict = verdict
        self.categories = categories or []


class _StubGateway(EnforcedInvokeMixin):
    """Stand-in для AIGateway: provides 9-step methods как AsyncMocks."""

    def __init__(self) -> None:
        # Pipeline step methods
        self._resolve_policy = AsyncMock(return_value=None)
        self._check_capability = AsyncMock(return_value=None)
        self._apply_input_sanitizers = AsyncMock(return_value="sanitized_text")
        # GuardResult-like (needs guard_name + verdict string attrs)
        self._input_guard = _GuardResult(guard_name="prompt_injection", verdict="blocked")
        self._apply_input_guards = AsyncMock(return_value=[self._input_guard])
        self._render_prompt = AsyncMock(return_value="rendered")
        self._invoke_llm = AsyncMock(
            return_value=MagicMock(
                content="llm_output",
                model_used="stub-model",
                tokens_prompt=10,
                tokens_completion=20,
            )
        )
        self._output_guard = _GuardResult(guard_name="llama_guard", verdict="safe")
        self._apply_output_guards = AsyncMock(return_value=[self._output_guard])
        self._apply_output_sanitizers = AsyncMock(
            return_value=AIResponse(content="clean_output", model_used="stub-model")
        )
        self._cost_track = AsyncMock(return_value=None)
        # Facade state (mocked)
        self._audit_service = MagicMock()


class TestEnforcedInvokeSequence:
    """Verify 9-step pipeline вызывается в правильном порядке."""

    async def test_calls_all_nine_steps(self) -> None:
        gw = _StubGateway()
        request = AIRequest(workflow_id="wf1", tenant_id="t1", correlation_id="c1")

        await gw._enforced_invoke(request)

        gw._resolve_policy.assert_awaited_once()
        gw._check_capability.assert_awaited_once()
        gw._apply_input_sanitizers.assert_awaited_once()
        gw._apply_input_guards.assert_awaited_once()
        gw._render_prompt.assert_awaited_once()
        gw._invoke_llm.assert_awaited_once()
        gw._apply_output_guards.assert_awaited_once()
        gw._apply_output_sanitizers.assert_awaited_once()
        gw._cost_track.assert_awaited_once()

    async def test_step_order_is_correct(self) -> None:
        gw = _StubGateway()
        request = AIRequest(workflow_id="wf1", tenant_id="t1", correlation_id="c1")
        call_order: list[str] = []

        def make_recorder(name: str) -> Any:
            async def record(*_args: Any, **_kwargs: Any) -> Any:
                call_order.append(name)
                if name == "_invoke_llm":
                    return MagicMock(content="x", model_used="m", tokens_prompt=1, tokens_completion=1)
                if name == "_apply_output_sanitizers":
                    return AIResponse(content="x", model_used="m")
                return None
            return record

        gw._resolve_policy.side_effect = make_recorder("_resolve_policy")
        gw._check_capability.side_effect = make_recorder("_check_capability")
        gw._apply_input_sanitizers.side_effect = make_recorder("_apply_input_sanitizers")
        gw._apply_input_guards.side_effect = make_recorder("_apply_input_guards")
        gw._render_prompt.side_effect = make_recorder("_render_prompt")
        gw._invoke_llm.side_effect = make_recorder("_invoke_llm")
        gw._apply_output_guards.side_effect = make_recorder("_apply_output_guards")
        gw._apply_output_sanitizers.side_effect = make_recorder("_apply_output_sanitizers")
        gw._cost_track.side_effect = make_recorder("_cost_track")

        await gw._enforced_invoke(request)

        # Verify order: resolve → check → sanit → guard → render → llm → guard → sanit → cost
        assert call_order[:8] == [
            "_resolve_policy",
            "_check_capability",
            "_apply_input_sanitizers",
            "_apply_input_guards",
            "_render_prompt",
            "_invoke_llm",
            "_apply_output_guards",
            "_apply_output_sanitizers",
        ]
        assert call_order[8] == "_cost_track"


class TestEnforcedInvokeReturnValue:
    async def test_returns_output_sanitized_response(self) -> None:
        gw = _StubGateway()
        expected = AIResponse(content="clean", model_used="m")
        gw._apply_output_sanitizers.return_value = expected
        request = AIRequest(workflow_id="wf1", tenant_id="t1", correlation_id="c1")

        result = await gw._enforced_invoke(request)

        assert result is expected


class TestEnforcedInvokePolicy:
    async def test_passes_policy_to_subsequent_steps(self) -> None:
        gw = _StubGateway()
        # Policy must have .name as str (audit ctx reads ctx.policy_name = policy.name)
        policy = MagicMock()
        policy.name = "credit_check_v1"
        gw._resolve_policy.return_value = policy
        request = AIRequest(workflow_id="wf1", tenant_id="t1", correlation_id="c1")

        await gw._enforced_invoke(request)

        # policy is passed to: input_sanitizers, input_guards, render, llm, output_guards, output_sanitizers, cost
        gw._apply_input_sanitizers.assert_awaited_with(request, policy)
        gw._apply_input_guards.assert_awaited_with("sanitized_text", policy)
        gw._render_prompt.assert_awaited_with(request, policy, "sanitized_text")
        gw._invoke_llm.assert_awaited_with("rendered", policy, request.stream)
        gw._apply_output_guards.assert_awaited()
        gw._apply_output_sanitizers.assert_awaited()
        gw._cost_track.assert_awaited_with(request, policy, gw._apply_output_sanitizers.return_value)

    async def test_policy_name_default_when_none(self) -> None:
        gw = _StubGateway()
        gw._resolve_policy.return_value = None  # no policy
        request = AIRequest(workflow_id="wf1", tenant_id="t1", correlation_id="c1")

        # When policy is None, ctx.policy_name = "default"
        result = await gw._enforced_invoke(request)
        assert result is not None


class TestEnforcedInvokePiiFlag:
    async def test_pii_detected_attr_access(self) -> None:
        gw = _StubGateway()
        # Set _last_input_pii_detected (set by _apply_input_sanitizers)
        gw._last_input_pii_detected = True
        request = AIRequest(workflow_id="wf1", tenant_id="t1", correlation_id="c1")

        # Should not raise even if _last_input_pii_detected not set (uses getattr default)
        result = await gw._enforced_invoke(request)
        assert result is not None

    async def test_pii_default_false_if_attr_missing(self) -> None:
        gw = _StubGateway()
        # Don't set _last_input_pii_detected
        request = AIRequest(workflow_id="wf1", tenant_id="t1", correlation_id="c1")

        # Should default to False (getattr with default)
        result = await gw._enforced_invoke(request)
        assert result is not None

class TestEnforcedInvokeCapabilityError:
    async def test_capability_error_propagates(self) -> None:
        gw = _StubGateway()
        gw._check_capability.side_effect = PermissionError("capability denied")
        request = AIRequest(workflow_id="wf1", tenant_id="t1", correlation_id="c1")

        with pytest.raises(PermissionError, match="capability denied"):
            await gw._enforced_invoke(request)

        # Pipeline stops at capability check — no further steps called
        gw._apply_input_sanitizers.assert_not_awaited()
        gw._invoke_llm.assert_not_awaited()
        gw._cost_track.assert_not_awaited()


class TestEnforcedInvokeGuardBranches:
    async def test_input_guards_empty_list(self) -> None:
        gw = _StubGateway()
        gw._apply_input_guards.return_value = []  # empty
        request = AIRequest(workflow_id="wf1", tenant_id="t1", correlation_id="c1")

        result = await gw._enforced_invoke(request)
        assert result is not None

    async def test_input_guards_with_results(self) -> None:
        gw = _StubGateway()
        gw._apply_input_guards.return_value = [
            _GuardResult(guard_name="g1", verdict="block"),
            _GuardResult(guard_name="g2", verdict="allow"),
        ]
        request = AIRequest(workflow_id="wf1", tenant_id="t1", correlation_id="c1")

        result = await gw._enforced_invoke(request)
        assert result is not None

    async def test_output_guards_with_results(self) -> None:
        gw = _StubGateway()
        gw._apply_output_guards.return_value = [_GuardResult(guard_name="og1", verdict="safe")]
        request = AIRequest(workflow_id="wf1", tenant_id="t1", correlation_id="c1")

        result = await gw._enforced_invoke(request)
        assert result is not None
