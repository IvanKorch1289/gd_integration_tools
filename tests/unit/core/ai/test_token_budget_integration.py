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
* Sprint 1.6 (P0-15): :class:`BudgetBackendUnavailable` (production
  fail-closed + Redis-outage) → :class:`BudgetEnforcementError` with
  503 body (per :func:`render_503`).

Используем :class:`InMemoryTokenBudgetBackend` (не Redis).
"""

from __future__ import annotations

from typing import Any

import pytest

from src.backend.core.ai.gateway_orchestrator_mixin import EnforcedInvokeMixin
from src.backend.core.config.features import feature_flags
from src.backend.core.tenancy.budget_enforcer import render_429, render_503
from src.backend.core.tenancy.token_budget import (
    BudgetBackendUnavailable,
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
        self, audit_service: _StubAuditService,
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
        self, audit_service: _StubAuditService,
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
        self, audit_service: _StubAuditService,
    ) -> None:
        """Actual > estimated → дополнительная reservation на diff."""

        class _Gateway(EnforcedInvokeMixin, _StubPipeline):
            _audit_service = audit_service
            _actual_tokens = (5000, 6000)  # prompts, completions

            async def _invoke_llm(  # type: ignore[override]
                self, rendered: Any, policy: Any, stream: bool,
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
        self, audit_service: _StubAuditService,
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
        self, audit_service: _StubAuditService,
    ) -> None:
        """Если actual (post-call diff) превышает hard_limit → BudgetExceeded."""

        class _Gateway(EnforcedInvokeMixin, _StubPipeline):
            _audit_service = audit_service

            async def _invoke_llm(  # type: ignore[override]
                self, rendered: Any, policy: Any, stream: bool,
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
        self, audit_service: _StubAuditService,
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
            tenant_id="t-x", used=200, hard_limit=100, period="daily",
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
        self, audit_service: _StubAuditService,
    ) -> None:
        """Без _token_budget attribute — no-op (backward-compat)."""

        class _Gateway(EnforcedInvokeMixin, _StubPipeline):
            _audit_service = audit_service

        gw = _Gateway()
        request = _build_request()
        snapshot = await gw._enforce_token_budget_pre_call(
            request, estimated_tokens=1000,
        )
        assert snapshot is None

    @pytest.mark.asyncio
    async def test_no_budget_via_dunder_getattr(
        self, audit_service: _StubAuditService,
    ) -> None:
        """``_token_budget=None`` → return None."""

        class _Gateway(EnforcedInvokeMixin, _StubPipeline):
            _audit_service = audit_service

        gw = _Gateway()
        gw._token_budget = None  # type: ignore[attr-defined]
        request = _build_request()
        snapshot = await gw._enforce_token_budget_pre_call(
            request, estimated_tokens=1000,
        )
        assert snapshot is None


# ─── Sprint 1.6 (P0-15) ──────────────────────────────────────────


class _FlakyBackend(InMemoryTokenBudgetBackend):
    """Backend с always-failing ``increment`` — имитирует Redis-outage."""

    async def increment(
        self, *, key: str, amount: int, ttl_seconds: int
    ) -> int:
        raise ConnectionError("simulated redis outage")


class TestBudgetBackendUnavailableFailClosed:
    """Sprint 1.6 (P0-15): production fail-closed + Redis-outage.

    Сценарий: ``feature_flags.token_budget_fail_closed=True`` (production
    override) + Redis недоступен → :class:`TokenBudget` бросает typed
    :class:`BudgetBackendUnavailable`. AIGateway pre/post-call должны
    поймать его и re-raise :class:`BudgetEnforcementError` с 503-body
    (через :func:`render_503`), чтобы endpoint-слой корректно
    отличал hard_limit breach (429) от infrastructure outage (503 +
    Retry-After).

    До Sprint 1.6: ``BudgetBackendUnavailable`` прорастал raw через
    pipeline → caller endpoint получал неподготовленный ``Exception``
    с потерей error-envelope.
    """

    @pytest.mark.asyncio
    async def test_pre_call_fail_closed_maps_to_503(
        self, audit_service: _StubAuditService, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """flag=ON + failing backend → BudgetEnforcementError с body=render_503."""

        class _Gateway(EnforcedInvokeMixin, _StubPipeline):
            _audit_service = audit_service

        monkeypatch.setattr(feature_flags, "token_budget_fail_closed", True)
        budget = TokenBudget(
            backend=_FlakyBackend(),
            default_config=TokenBudgetConfig(
                soft_limit=100,
                hard_limit=200,
                period=BudgetPeriod.DAILY,
                fail_mode="open",  # per-tenant open, но flag=ON → fail-closed
            ),
        )
        gw = _Gateway()
        gw._token_budget = budget  # type: ignore[attr-defined]
        request = _build_request(tenant_id="t-redis-down")

        with pytest.raises(BudgetEnforcementError) as ctx:
            await gw._enforce_token_budget_pre_call(
                request, estimated_tokens=100
            )
        body = ctx.value.body
        assert body["error"] == "token_budget_backend_unavailable"
        assert body["tenant_id"] == "t-redis-down"
        assert body["backend"] == "token_budget"
        assert "message" in body

    @pytest.mark.asyncio
    async def test_pre_call_flag_off_preserves_fail_open(
        self, audit_service: _StubAuditService, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """flag=OFF + failing backend + per-tenant open → no raise (fail-open).

        Backward-compat invariant: dev/test environments с flag=OFF
        продолжают работать как раньше (fail-open swallow).
        """

        class _Gateway(EnforcedInvokeMixin, _StubPipeline):
            _audit_service = audit_service

        monkeypatch.setattr(feature_flags, "token_budget_fail_closed", False)
        budget = TokenBudget(
            backend=_FlakyBackend(),
            default_config=TokenBudgetConfig(
                soft_limit=100,
                hard_limit=200,
                period=BudgetPeriod.DAILY,
                fail_mode="open",
            ),
        )
        gw = _Gateway()
        gw._token_budget = budget  # type: ignore[attr-defined]
        request = _build_request(tenant_id="t-dev")

        snapshot = await gw._enforce_token_budget_pre_call(
            request, estimated_tokens=100
        )
        # Fail-open: вернулся BudgetSnapshot с used=0, без raise.
        assert snapshot is not None
        assert snapshot.used == 0

    @pytest.mark.asyncio
    async def test_post_call_fail_closed_maps_to_503(
        self, audit_service: _StubAuditService, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Post-call correction с actual > estimated + fail-closed → 503 body.

        Реальный сценарий: pre-call прошёл (Redis ещё жил), LLM ответил
        с большим actual_tokens, post-call пытается дорезервировать diff —
        и тут Redis умирает. Без Sprint 1.6 — exception прорастал bare.
        """

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

        monkeypatch.setattr(feature_flags, "token_budget_fail_closed", True)
        budget = TokenBudget(
            backend=_FlakyBackend(),
            default_config=TokenBudgetConfig(
                soft_limit=100,
                hard_limit=200,
                period=BudgetPeriod.DAILY,
                fail_mode="open",
            ),
        )
        gw = _Gateway()
        gw._token_budget = budget  # type: ignore[attr-defined]
        request = _build_request(tenant_id="t-post-outage")

        # Pre-call пройдёт успешно (тут бэкенд ещё работал до pre-call).
        # Post-call споткнётся на refинансировании — это и есть целевой тест.
        # Прямой вызов post-call с broken budget → ожидаем 503-body.
        completion = type(
            "_C",
            (),
            {
                "tokens_prompt": 5000,
                "tokens_completion": 5000,
            },
        )()
        with pytest.raises(BudgetEnforcementError) as ctx:
            await gw._enforce_token_budget_post_call(
                request, completion, estimated_tokens=200
            )
        body = ctx.value.body
        assert body["error"] == "token_budget_backend_unavailable"
        assert body["tenant_id"] == "t-post-outage"
        assert body["backend"] == "token_budget"

    @pytest.mark.asyncio
    async def test_per_tenant_fail_closed_via_config(
        self, audit_service: _StubAuditService, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Per-tenant fail_mode='closed' (без feature_flag) → 503 body.

        Backward-compat: TokenBudget.fail_mode='closed' существовал до
        feature_flag. AIGateway должен одинаково маппить оба пути.
        """

        class _Gateway(EnforcedInvokeMixin, _StubPipeline):
            _audit_service = audit_service

        # flag=OFF, но per-tenant = closed.
        monkeypatch.setattr(feature_flags, "token_budget_fail_closed", False)
        budget = TokenBudget(
            backend=_FlakyBackend(),
            default_config=TokenBudgetConfig(
                soft_limit=100,
                hard_limit=200,
                period=BudgetPeriod.DAILY,
                fail_mode="closed",
            ),
        )
        gw = _Gateway()
        gw._token_budget = budget  # type: ignore[attr-defined]
        request = _build_request(tenant_id="t-per-tenant-closed")

        with pytest.raises(BudgetEnforcementError) as ctx:
            await gw._enforce_token_budget_pre_call(
                request, estimated_tokens=100
            )
        assert ctx.value.body["error"] == "token_budget_backend_unavailable"

    def test_render_503_shape(self) -> None:
        """render_503 возвращает JSON-ready dict с error+tenant_id+backend."""
        exc = BudgetBackendUnavailable(backend="token_budget", tenant_id="t-1")
        body = render_503(exc)
        assert body["error"] == "token_budget_backend_unavailable"
        assert body["tenant_id"] == "t-1"
        assert body["backend"] == "token_budget"
        assert "message" in body

    def test_render_503_distinct_from_render_429(self) -> None:
        """render_503 и render_429 имеют разные error-keys (caller dispatch)."""
        backend_exc = BudgetBackendUnavailable(
            backend="token_budget", tenant_id="t-1"
        )
        hard_exc = BudgetExceeded(
            tenant_id="t-1", used=200, hard_limit=100, period="daily"
        )
        body_503 = render_503(backend_exc)
        body_429 = render_429(hard_exc)
        # 503 — infrastructure outage (Retry-After), 429 — caller throttling.
        assert body_503["error"] != body_429["error"]
        assert body_503["error"] == "token_budget_backend_unavailable"
        assert body_429["error"] == "token_budget_exceeded"
