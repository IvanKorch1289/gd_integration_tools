"""Unit-тесты ``ObservabilityMixin`` — coverage ratchet (S48 W9).

observability_mixin.py — S56 W2 extraction: audit + cost tracking для
:class:`AIGateway` (audit emit + cost record + budget enforce).
S44 W32 baseline: 20% coverage (33/45 missing).

Цель slice: поднять до максимального coverage на 2 публичных методах
(_audit_emit, _cost_track) через AsyncMock + duck-typing для self.* attrs.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.core.ai.gateway_models import AIRequest, AIResponse
from src.backend.core.ai.gateway_pipeline_mixin.observability_mixin import (
    ObservabilityMixin,
)


class _StubMixin:
    """Минимальный stand-in для AIGateway — реализует только attrs нужные mixin'у.

    ObservabilityMixin требует: self._audit_service, self._cost_tracker,
    self._provider_from_model.
    """

    _audit_service = None
    _cost_tracker = None

    def _provider_from_model(self, model: str) -> str:
        return "stub_provider"

    def _audit_emit(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        # Bound method injection point.
        return ObservabilityMixin._audit_emit.__get__(self)(*args, **kwargs)

    def _cost_track(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        return ObservabilityMixin._cost_track.__get__(self)(*args, **kwargs)


def _req_resp(cost_usd: float = 0.05) -> tuple[AIRequest, AIResponse]:
    req = AIRequest(
        workflow_id="wf-1",
        tenant_id="t-1",
        correlation_id="corr-1",
        prompt_inline="hi",
    )
    resp = AIResponse(content="hello", model_used="stub", cost_usd=cost_usd)
    return req, resp


@pytest.mark.unit
class TestObservabilityMixinAudit:
    """``_audit_emit`` — happy path + fail-closed fallback."""

    @pytest.mark.asyncio
    async def test_audit_emit_with_explicit_service(self) -> None:
        """explicit ``_audit_service`` → прямой вызов ``emit()``."""
        audit = AsyncMock()
        audit.emit = AsyncMock()
        mixin = _StubMixin()
        mixin._audit_service = audit

        req, resp = _req_resp()
        await mixin._audit_emit(req, None, resp)

        assert audit.emit.call_count == 1

    @pytest.mark.asyncio
    async def test_audit_emit_lazy_resolves_service(self) -> None:
        """``_audit_service=None`` → резолвит через ``get_unified_audit_service()``."""
        lazy_audit = AsyncMock()
        lazy_audit.emit = AsyncMock()
        mixin = _StubMixin()
        mixin._audit_service = None

        with patch(
            "src.backend.core.audit.facade.audit_service.get_unified_audit_service",
            return_value=lazy_audit,
        ):
            req, resp = _req_resp()
            await mixin._audit_emit(req, None, resp)

        assert lazy_audit.emit.call_count == 1

    @pytest.mark.asyncio
    async def test_audit_emit_swallows_lazy_resolution_failure(self) -> None:
        """Если lazy resolve fails → log debug + return (no raise)."""
        mixin = _StubMixin()
        mixin._audit_service = None

        with patch(
            "src.backend.core.audit.facade.audit_service.get_unified_audit_service",
            side_effect=ImportError("audit facade missing"),
        ):
            req, resp = _req_resp()
            # Не должно raise.
            await mixin._audit_emit(req, None, resp)


@pytest.mark.unit
class TestObservabilityMixinCost:
    """``_cost_track`` — happy path + no-op fallback + zero-cost skip."""

    @pytest.mark.asyncio
    async def test_cost_track_no_tracker_is_noop(self) -> None:
        """``_cost_tracker=None`` → silent return (no raise, no log)."""
        mixin = _StubMixin()
        mixin._cost_tracker = None
        req, resp = _req_resp()
        # Не должно raise.
        await mixin._cost_track(req, None, resp)

    @pytest.mark.asyncio
    async def test_cost_track_with_tracker_records(self) -> None:
        """Tracker с record_cost + record_tokens → оба вызваны."""
        tracker = MagicMock()
        tracker.record_cost = MagicMock()
        tracker.record_tokens = MagicMock()

        mixin = _StubMixin()
        mixin._cost_tracker = tracker
        req, resp = _req_resp()
        await mixin._cost_track(req, None, resp)

        assert tracker.record_cost.call_count == 1
        assert tracker.record_tokens.call_count == 1

    @pytest.mark.asyncio
    async def test_cost_track_zero_cost_skips_record_cost(self) -> None:
        """``cost_usd=0`` → ``record_cost`` не вызывается (только tokens)."""
        tracker = MagicMock()
        tracker.record_cost = MagicMock()
        tracker.record_tokens = MagicMock()

        mixin = _StubMixin()
        mixin._cost_tracker = tracker
        req = AIRequest(
            workflow_id="wf-1",
            tenant_id="t-1",
            correlation_id="corr-1",
            prompt_inline="hi",
        )
        resp = AIResponse(content="hello", model_used="stub", cost_usd=0.0)
        await mixin._cost_track(req, None, resp)

        assert tracker.record_cost.call_count == 0
        assert tracker.record_tokens.call_count == 1
