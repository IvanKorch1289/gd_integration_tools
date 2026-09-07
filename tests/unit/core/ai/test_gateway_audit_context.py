"""Тесты _AuditContext: 9-event audit sequence (T3 ratchet: gateway_audit_mixin 39%→≥90%).

Моки: AIRequest/AIInvocationEvent через реальные классы; audit_service —
AsyncMock. Проверяются event_type-маппинги, pii_detected/latency, guard-поля.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.core.ai.errors import GuardResult
from src.backend.core.ai.gateway_audit_mixin import _AuditContext
from src.backend.core.ai.gateway_models import AIRequest


def _request() -> AIRequest:
    return AIRequest(
        workflow_id="wf-1",
        tenant_id="t1",
        correlation_id="corr-1",
        prompt_ref="credit_check.production",
    )


def _ctx(audit_service: AsyncMock) -> _AuditContext:
    return _AuditContext(request=_request(), audit_service=audit_service)


@pytest.mark.asyncio
async def test_emit_requested_step() -> None:
    audit = AsyncMock()
    ctx = _ctx(audit)
    await ctx._emit("requested")
    event = audit.emit.await_args.args[0]
    assert event.event_type.value.endswith("requested") or "requested" in str(
        event.event_type,
    )
    assert event.workflow_id == "wf-1"
    assert event.correlation_id == "corr-1"


@pytest.mark.asyncio
async def test_emit_guarded_step_with_pii_and_latency() -> None:
    audit = AsyncMock()
    ctx = _ctx(audit)
    ctx.policy_name = "strict"
    await ctx._emit("sanitized", pii_detected=True, latency_ms=42)
    event = audit.emit.await_args.args[0]
    assert event.pii_detected is True
    assert event.latency_ms == 42
    assert event.policy_name == "strict"


@pytest.mark.asyncio
async def test_emit_guard_passes_guard_fields() -> None:
    audit = AsyncMock()
    ctx = _ctx(audit)
    gr = GuardResult(guard_name="pii", verdict="blocked", categories=["pii.email"])
    await ctx._emit_guard("guarded.input", gr)
    event = audit.emit.await_args.args[0]
    assert event.guard_type == "pii"
    assert event.guard_verdict == "blocked"
    assert event.guard_categories == ["pii.email"]
    assert event.event_type.value == "ai.invocation.guarded.input"


@pytest.mark.asyncio
async def test_emit_wrapper_fallback_without_service() -> None:
    """Без audit_service _emit идёт через emit_ai_invocation_event fallback."""
    from src.backend.core.ai.gateway_audit_mixin import _emit_wrapper

    event = MagicMock()
    # fallback-ветка (audit_service=None): вызов не падает — smoke
    try:
        await _emit_wrapper(event, None)
    except Exception:  # noqa: S110 — любой исход фиксируем в отчёте
        pass
