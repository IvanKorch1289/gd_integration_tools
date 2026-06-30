"""Integration tests for S172 M4 ARC-007 — Token budget enforcement in
AIGateway pipeline.

Tests the integration of :class:`TokenBudget` enforcement into the
9-step pipeline (`gateway_orchestrator_mixin.py`).

Key paths:
* ``_enforce_token_budget_pre_call`` — reservation before LLM call.
* ``_enforce_token_budget_post_call`` — actual usage correction.
* ``_token_budget`` attribute on AIGateway — if missing → no-op
  (backward-compat with callers that don't wire budget).
* Empty ``tenant_id`` → skip (current ARC-007 design).
* :class:`BudgetExceeded` → :class:`BudgetEnforcementError` raised.

Используем :class:`InMemoryTokenBudgetBackend` (не Redis).
"""

from __future__ import annotations

from typing import Any

import pytest

from src.backend.core.ai.gateway_orchestrator_mixin import EnforcedInvokeMixin
from src.backend.core.tenancy.budget_enforcer import render_429
from src.backend.core.tenancy.token_budget import (
    BudgetEnforcementError,
    BudgetExceeded,
    BudgetPeriod,
    InMemoryTokenBudgetBackend,
    TokenBudget,
    TokenBudgetConfig,
)

# ─── Test harness ───────────────────────────────────────────────────


class _StubPipeline:
    """Minimal stub for PipelineStepsMixin.

    Локальный — используется только для вызова _enforced_invoke (ARC-007
    integration tests). Mixin наследуется через __init_subclass__ proxy.
    """

    async def _resolve_policy(self, request: Any) -> Any:  # type: ignore[no-untyped-def]
        return None

    async def _check_capability(self, request: Any) -> None:  # type: ignore[no-untyped-def]
        return None

    async def _apply_input_sanitizers(self, request: Any, policy: Any) -> str:  # type: ignore[no-untyped-def]
        return getattr(request, "prompt_inline", "") or ""

    async def _apply_input_guards(self, text: str, policy: Any) -> list:  # type: ignore[no-untyped-def]
        return []

    async def _render_prompt(self, request: Any, policy: Any, sanitized: str) -> Any:  # type: ignore[no-untyped-def]
        class _R:
            prompt_text = sanitized or ""

        return _R()

    async def _invoke_llm(self, rendered: Any, policy: Any, stream: bool) -> Any:  # type: ignore[no-untyped-def]
        class _C:
            content = "stub"
            tokens_prompt = 100
            tokens_completion = 50
            cost_usd = 0.0
            model_used = "stub"
            pii_detected = False
            guardrails_verdict: dict[str, str] = {"output": "safe"}

        return _C()

    async def _apply_output_guards(self, completion: Any, policy: Any) -> list:  # type: ignore[no-untyped-def]
        return []

    async def _apply_output_sanitizers(self, completion: Any, policy: Any) -> Any:  # type: ignore[no-untyped-def]
        return completion

    async def _cost_track(self, request: Any, policy: Any, response: Any) -> None:  # type: ignore[no-untyped-def]
        return None


class _StubAuditService:
    """Stub для audit_service — record events emit'ов."""

    def __init__(self) -> None:
        self.events: list[Any] = []

    async def emit(self, event: Any) -> None:
        self.events.append(event)


@pytest.fixture
def audit_service() -> _StubAuditService:
    return _StubAuditService()


def _build_request(**kwargs: Any) -> Any:  # type: ignore[no-untyped-def]
    """Build minimal AIRequest для integration test."""
    from src.backend.core.ai.gateway_models import AIRequest

    defaults: dict[str, Any] = {
        "workflow_id": "test_workflow",
        "tenant_id": "tenant-1",
        "correlation_id": "corr-1",
        "prompt_inline": "Hello, world!",
        "context": {},
        "stream": False,
        "tool_name": None,
    }
    defaults.update(kwargs)
    return AIRequest(**defaults)  # type: ignore[arg-type]


def _build_budget(
    *,
    soft_limit: int = 1000,
    hard_limit: int = 2000,
    period: str = BudgetPeriod.DAILY,
) -> TokenBudget:
    """Build TokenBudget с in-memory backend."""
    return TokenBudget(
        backend=InMemoryTokenBudgetBackend(),
        default_config=TokenBudgetConfig(
            soft_limit=soft_limit,
            hard_limit=hard_limit,
            period=period,
        ),
    )


# ─── Tests ──────────────────────────────────────────────────────────


class TestBudgetNotConfigured:
    """Без ``_token_budget`` attribute — pipeline should pass-through no-op."""

    @pytest.mark.asyncio
    async def test_no_budget_passes_through(
        self, audit_service: _StubAuditService
    ) -> None:
        """Pipeline без _token_budget → no exception (backward-compat)."""

        class _Gateway(EnforcedInvokeMixin, _StubPipeline):
            _audit_service = audit_service

        gw = _Gateway()
        request = _build_request()
        # No _token_budget set → pre/post enforcement должен no-op.
        response = await gw._enforced_invoke(request)
        assert response.content == "stub"


class TestBudgetEnforced:
    """С _token_budget настроенным — проверка reservation + correction."""

    @pytest.mark.asyncio
    async def test_pre_call_reserves(
        self, audit_service: _StubAuditService
    ) -> None:
        """Pre-call reserves estimated tokens + post-call corrects."""

        class _Gateway(EnforcedInvokeMixin, _StubPipeline):
            _audit_service = audit_service

        budget = _build_budget()
        gw = _Gateway()
        gw._token_budget = budget  # type: ignore[attr-defined]

        request = _build_request(tenant_id="t-pre-post")
        # Invoke full pipeline.
        await gw._enforced_invoke(request)

        # Post-call: actual tokens (100+50=150) reserved. Total = estimated
        # (prompt_inline "Hello, world!" ~4 chars + 200 = 200) + diff(150-200 = -50,
        # non-positive → no further reserve). Wait — len("Hello, world!") = 13,
        # 13/4 = 3, + 200 = 203. estimated = 203. actual = 150. diff = -53 ≤ 0 → snapshot only.
        snapshot = await budget.snapshot(tenant_id="t-pre-post")
        # Min 0, estimated 203 reserved at pre-call.
        assert snapshot.used == 203

    @pytest.mark.asyncio
    async def test_actual_exceeds_estimated_extra_reserved(
        self, audit_service: _StubAuditService
    ) -> None:
        """Actual > estimated → дополнительная reservation на diff."""

        class _Gateway(EnforcedInvokeMixin, _StubPipeline):
            _audit_service = audit_service
            _actual_tokens = (5000, 6000)  # prompts, completions

            async def _invoke_llm(  # type: ignore[override]
                self, rendered: Any, policy: Any, stream: bool
            ) -> Any:
                class _C:
                    content = "stub"
                    tokens_prompt = self._actual_tokens[0]
                    tokens_completion = self._actual_tokens[1]
                    cost_usd = 0.0
                    model_used = "stub"
                    pii_detected = False
                    guardrails_verdict: dict[str, str] = {"output": "safe"}

                return _C()

        budget = _build_budget(hard_limit=20_000)
        gw = _Gateway()
        gw._token_budget = budget  # type: ignore[attr-defined]

        request = _build_request(tenant_id="t-overflow")
        await gw._enforced_invoke(request)

        # estimated: len("Hello, world!") // 4 + 200 = 3 + 200 = 203.
        # actual: 5000 + 6000 = 11000.
        # diff = 11000 - 203 = 10797.
        # Total used = 203 + 10797 = 11000.
        snapshot = await budget.snapshot(tenant_id="t-overflow")
        assert snapshot.used == 11_000

    @pytest.mark.asyncio
    async def test_hard_limit_pre_call_raises(
        self, audit_service: _StubAuditService
    ) -> None:
        """Если estimated уже превышает hard_limit → BudgetExceeded."""

        class _Gateway(EnforcedInvokeMixin, _StubPipeline):
            _audit_service = audit_service
            _audit_ctx: Any = None

        gw = _Gateway()
        gw._token_budget = _build_budget(hard_limit=10)  # очень маленький limit

        request = _build_request(
            tenant_id="t-pre-breach",
            prompt_inline="X" * 1000,  # 1000 chars → ~250 estimated
        )

        with pytest.raises(BudgetEnforcementError) as ctx:
            await gw._enforced_invoke(request)
        # Body JSON shape (per render_429 contract).
        assert "tenant_id" in ctx.value.body
        assert ctx.value.body["error"] == "token_budget_exceeded"

    @pytest.mark.asyncio
    async def test_hard_limit_post_call_raises(
        self, audit_service: _StubAuditService
    ) -> None:
        """Если actual (post-call diff) превышает hard_limit → BudgetExceeded."""

        class _Gateway(EnforcedInvokeMixin, _StubPipeline):
            _audit_service = audit_service

            async def _invoke_llm(  # type: ignore[override]
                self, rendered: Any, policy: Any, stream: bool
            ) -> Any:
                class _C:
                    content = "stub"
                    tokens_prompt = 5000
                    tokens_completion = 5000
                    cost_usd = 0.0
                    model_used = "stub"
                    pii_detected = False
                    guardrails_verdict: dict[str, str] = {"output": "safe"}

                return _C()

        gw = _Gateway()
        gw._token_budget = _build_budget(hard_limit=2000)

        request = _build_request(tenant_id="t-post-breach")

        with pytest.raises(BudgetEnforcementError) as ctx:
            await gw._enforced_invoke(request)
        # used = estimated 203 + diff(10000-203 = 9797) = 10000 > hard_limit 2000.
        assert ctx.value.body["hard_limit"] == 2000

    @pytest.mark.asyncio
    async def test_empty_tenant_id_skips(
        self, audit_service: _StubAuditService
    ) -> None:
        """Empty ``tenant_id`` → budget skipped (no error)."""

        class _Gateway(EnforcedInvokeMixin, _StubPipeline):
            _audit_service = audit_service

        gw = _Gateway()
        gw._token_budget = _build_budget()
        # Force empty tenant_id. Use monkeypatching to bypass dataclass immutability.
        from src.backend.core.ai.gateway_models import AIRequest

        request = AIRequest(
            workflow_id="test_workflow",
            tenant_id="",  # empty
            correlation_id="corr-1",
            prompt_inline="Hello",
        )
        response = await gw._enforced_invoke(request)
        assert response.content == "stub"


class TestRender429Contract:
    """Verify render_429 JSON contract (callers depend on it)."""

    def test_render_429_shape(self) -> None:
        exc = BudgetExceeded(
            tenant_id="t-x", used=200, hard_limit=100, period="daily"
        )
        body = render_429(exc)
        assert body["error"] == "token_budget_exceeded"
        assert body["tenant_id"] == "t-x"
        assert body["used_tokens"] == 200
        assert body["hard_limit"] == 100
        assert body["period"] == "daily"
        assert "message" in body


class TestPreCallHelperUnit:
    """Unit-тесты для ``_enforce_token_budget_pre_call`` helper отдельно."""

    @pytest.mark.asyncio
    async def test_no_budget_attribute_returns_none(
        self, audit_service: _StubAuditService
    ) -> None:
        """Без _token_budget attribute — no-op (backward-compat)."""

        class _Gateway(EnforcedInvokeMixin, _StubPipeline):
            _audit_service = audit_service

        gw = _Gateway()
        request = _build_request()
        snapshot = await gw._enforce_token_budget_pre_call(
            request, estimated_tokens=1000
        )
        assert snapshot is None

    @pytest.mark.asyncio
    async def test_no_budget_via_dunder_getattr(
        self, audit_service: _StubAuditService
    ) -> None:
        """``_token_budget=None`` → return None."""

        class _Gateway(EnforcedInvokeMixin, _StubPipeline):
            _audit_service = audit_service

        gw = _Gateway()
        gw._token_budget = None  # type: ignore[attr-defined]
        request = _build_request()
        snapshot = await gw._enforce_token_budget_pre_call(
            request, estimated_tokens=1000
        )
        assert snapshot is None
