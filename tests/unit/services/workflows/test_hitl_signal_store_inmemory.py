"""Тесты InMemoryHitlSignalStore — покрытие краевых случаев (T3 ratchet).

Дополняет test_hitl_service.py (там store тестируется через сервис):
здесь — напрямую контракт Protocol-реализации: KeyError/ValueError в
mark_resolved, wait_for timeout/already-resolved, tenant-фильтр, сортировка.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from src.backend.services.workflows.hitl_models import HitlPendingSignal
from src.backend.services.workflows.hitl_signal_store import InMemoryHitlSignalStore


def _signal(signal_id: str, *, tenant_id: str = "t1", minutes_ago: int = 0) -> HitlPendingSignal:
    return HitlPendingSignal(
        signal_id=signal_id,
        workflow_id=f"wf-{signal_id}",
        tenant_id=tenant_id,
        signal_name="hitl_approve",
        initiator="initiator-1",
        title=f"Signal {signal_id}",
        created_at=datetime.now(UTC) - timedelta(minutes=minutes_ago),
    )


@pytest.mark.asyncio
async def test_get_missing_returns_none() -> None:
    store = InMemoryHitlSignalStore()
    assert await store.get("nope") is None


@pytest.mark.asyncio
async def test_mark_resolved_missing_raises_key_error() -> None:
    store = InMemoryHitlSignalStore()
    with pytest.raises(KeyError):
        await store.mark_resolved("nope", action="approve", resolved_by="op")


@pytest.mark.asyncio
async def test_mark_resolved_twice_raises_value_error() -> None:
    store = InMemoryHitlSignalStore()
    sig = _signal("s1")
    await store.put(sig)
    await store.mark_resolved("s1", action="approve", resolved_by="op")
    with pytest.raises(ValueError, match="already resolved"):
        await store.mark_resolved("s1", action="reject", resolved_by="op2")


@pytest.mark.asyncio
async def test_wait_for_timeout_returns_false() -> None:
    store = InMemoryHitlSignalStore()
    await store.put(_signal("s1"))
    # Никто не резолвит — wait_for упирается в timeout.
    assert await store.wait_for("s1", timeout=0.05) is False


@pytest.mark.asyncio
async def test_wait_for_already_resolved_returns_true_immediately() -> None:
    store = InMemoryHitlSignalStore()
    sig = _signal("s1")
    await store.put(sig)
    await store.mark_resolved("s1", action="approve", resolved_by="op")
    assert await store.wait_for("s1", timeout=1.0) is True


@pytest.mark.asyncio
async def test_list_pending_filters_tenant_and_sorts() -> None:
    store = InMemoryHitlSignalStore()
    # s3 создан «раньше» всех, s2 — из другого тенанта.
    await store.put(_signal("s3", minutes_ago=10))
    await store.put(_signal("s1", minutes_ago=2))
    await store.put(_signal("s2", tenant_id="t2"))
    sig1 = _signal("s1", minutes_ago=2)
    sig1.resolved_at = datetime.now(UTC)
    await store.put(sig1)

    pending = await store.list_pending()
    ids = [s.signal_id for s in pending]
    assert "s1" not in ids, "resolved-сигнал не должен попадать в pending"
    assert {"s2", "s3"} <= set(ids)

    tenant_only = await store.list_pending(tenant_id="t2")
    assert [s.signal_id for s in tenant_only] == ["s2"]

    ordered = await store.list_pending()
    created = [s.created_at for s in ordered]
    assert created == sorted(created)  # сортировка по created_at


@pytest.mark.asyncio
async def test_resolve_via_store_sets_is_resolved_and_fields() -> None:
    store = InMemoryHitlSignalStore()
    sig = _signal("s1")
    await store.put(sig)
    resolved = await store.mark_resolved("s1", action="reject", resolved_by="op1")
    assert resolved.is_resolved is True
    assert resolved.resolved_action == "reject"
    assert resolved.resolved_by == "op1"
    assert resolved.resolved_at is not None
