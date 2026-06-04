"""Unit-тесты GuardrailsMetricsService (Sprint 9 K4 W5)."""

from __future__ import annotations

import pytest

from src.backend.services.ai.guardrails_metrics import (
    GuardrailReason,
    GuardrailVerdict,
    GuardrailsMetricsService,
)


@pytest.mark.asyncio
async def test_record_allow() -> None:
    svc = GuardrailsMetricsService()
    await svc.record(tenant_id="t-1", verdict=GuardrailVerdict.ALLOW)
    snap = await svc.snapshot("t-1")
    assert snap.allow == 1
    assert snap.block == 0
    assert snap.total == 1


@pytest.mark.asyncio
async def test_record_block_with_reason() -> None:
    svc = GuardrailsMetricsService()
    await svc.record(
        tenant_id="t-1", verdict=GuardrailVerdict.BLOCK, reason=GuardrailReason.PII
    )
    snap = await svc.snapshot("t-1")
    assert snap.block == 1
    assert snap.by_reason["pii"] == 1
    assert snap.block_rate == 1.0


@pytest.mark.asyncio
async def test_mark_false_positive() -> None:
    svc = GuardrailsMetricsService()
    await svc.record(tenant_id="t-1", verdict=GuardrailVerdict.BLOCK)
    await svc.record(tenant_id="t-1", verdict=GuardrailVerdict.BLOCK)
    await svc.mark_false_positive(tenant_id="t-1", count=1)
    snap = await svc.snapshot("t-1")
    assert snap.false_positives == 1
    assert snap.false_positive_rate == 0.5


@pytest.mark.asyncio
async def test_list_all_sorted() -> None:
    svc = GuardrailsMetricsService()
    await svc.record(tenant_id="t-b", verdict=GuardrailVerdict.ALLOW)
    await svc.record(tenant_id="t-a", verdict=GuardrailVerdict.ALLOW)
    items = await svc.list_all()
    assert [m.tenant_id for m in items] == ["t-a", "t-b"]


@pytest.mark.asyncio
async def test_reset_specific_tenant() -> None:
    svc = GuardrailsMetricsService()
    await svc.record(tenant_id="t-1", verdict=GuardrailVerdict.BLOCK)
    await svc.record(tenant_id="t-2", verdict=GuardrailVerdict.BLOCK)
    await svc.reset("t-1")
    items = await svc.list_all()
    assert [m.tenant_id for m in items] == ["t-2"]


@pytest.mark.asyncio
async def test_reset_all() -> None:
    svc = GuardrailsMetricsService()
    await svc.record(tenant_id="t-1", verdict=GuardrailVerdict.BLOCK)
    await svc.reset(None)
    items = await svc.list_all()
    assert items == []


@pytest.mark.asyncio
async def test_block_rate_zero_when_no_total() -> None:
    svc = GuardrailsMetricsService()
    snap = await svc.snapshot("t-new")
    assert snap.block_rate == 0.0
    assert snap.false_positive_rate == 0.0


@pytest.mark.asyncio
async def test_redact_verdict_increments_redact() -> None:
    svc = GuardrailsMetricsService()
    await svc.record(
        tenant_id="t-1", verdict=GuardrailVerdict.REDACT, reason=GuardrailReason.PII
    )
    snap = await svc.snapshot("t-1")
    assert snap.redact == 1
    assert snap.by_reason["pii"] == 1
