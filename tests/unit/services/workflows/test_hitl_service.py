"""Unit-тесты HitlService + InMemoryHitlSignalStore (Sprint 9 K3 W2)."""

from __future__ import annotations

import pytest

from src.backend.services.workflows.hitl_service import (
    HitlAction,
    HitlPendingSignal,
    HitlService,
    InMemoryHitlSignalStore,
)


def _signal(signal_id: str, tenant: str = "t-1", wf: str = "wf-1") -> HitlPendingSignal:
    return HitlPendingSignal(
        signal_id=signal_id,
        workflow_id=wf,
        tenant_id=tenant,
        signal_name="hitl_approve",
        initiator="user@bank.local",
        title="Approve credit",
        payload={"amount": 100000},
    )


@pytest.mark.asyncio
async def test_register_and_list_pending() -> None:
    svc = HitlService(store=InMemoryHitlSignalStore())
    await svc.register_pending(_signal("s-1"))
    await svc.register_pending(_signal("s-2"))
    items = await svc.list_pending()
    assert len(items) == 2
    assert {s.signal_id for s in items} == {"s-1", "s-2"}


@pytest.mark.asyncio
async def test_list_pending_filtered_by_tenant() -> None:
    svc = HitlService(store=InMemoryHitlSignalStore())
    await svc.register_pending(_signal("s-1", tenant="t-a"))
    await svc.register_pending(_signal("s-2", tenant="t-b"))
    items = await svc.list_pending(tenant_id="t-a")
    assert len(items) == 1
    assert items[0].signal_id == "s-1"


@pytest.mark.asyncio
async def test_resolve_approve_with_facade_calls_signal() -> None:
    calls: list[dict] = []

    class _FakeFacade:
        async def signal(
            self, *, caller: str, handle, signal_name: str, payload: dict
        ) -> None:
            calls.append(
                {
                    "caller": caller,
                    "handle": handle.workflow_id,
                    "signal_name": signal_name,
                    "payload": payload,
                }
            )

    svc = HitlService(store=InMemoryHitlSignalStore(), workflow_facade=_FakeFacade())
    await svc.register_pending(_signal("s-1"))
    resolved = await svc.resolve(
        signal_id="s-1",
        action=HitlAction.APPROVE,
        resolved_by="operator@bank.local",
        payload={"comment": "ok"},
    )
    assert resolved.is_resolved
    assert resolved.resolved_action == HitlAction.APPROVE
    assert calls[0]["signal_name"] == "hitl_approve"
    assert calls[0]["payload"]["action"] == HitlAction.APPROVE


@pytest.mark.asyncio
async def test_resolve_invalid_action_raises() -> None:
    svc = HitlService(store=InMemoryHitlSignalStore())
    await svc.register_pending(_signal("s-1"))
    with pytest.raises(ValueError, match="Invalid action"):
        await svc.resolve(signal_id="s-1", action="bogus", resolved_by="op")


@pytest.mark.asyncio
async def test_double_resolve_raises() -> None:
    svc = HitlService(store=InMemoryHitlSignalStore())
    await svc.register_pending(_signal("s-1"))
    await svc.resolve(signal_id="s-1", action=HitlAction.APPROVE, resolved_by="op-1")
    with pytest.raises(ValueError, match="already resolved"):
        await svc.resolve(signal_id="s-1", action=HitlAction.REJECT, resolved_by="op-2")


@pytest.mark.asyncio
async def test_resolve_unknown_raises_key_error() -> None:
    svc = HitlService(store=InMemoryHitlSignalStore())
    with pytest.raises(KeyError):
        await svc.resolve(
            signal_id="ghost", action=HitlAction.APPROVE, resolved_by="op"
        )


def test_to_dict_shape() -> None:
    sig = _signal("s-1")
    body = sig.to_dict()
    assert body["signal_id"] == "s-1"
    assert body["is_resolved"] is False
    assert body["resolved_at"] is None
    assert body["payload"]["amount"] == 100000
