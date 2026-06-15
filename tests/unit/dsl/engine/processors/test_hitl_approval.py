"""Unit-тесты HitlApprovalProcessor (S133 W4).

Покрытие:
    * approve → exchange.properties["hitl_approval"].
    * reject → exchange.failed с причиной.
    * timeout → exchange.failed по таймауту.
    * request_info → повторная регистрация и ожидание approve.
"""

# ruff: noqa: S101

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange, Message
from src.backend.dsl.engine.processors.hitl_approval import HitlApprovalProcessor
from src.backend.services.workflows.hitl_service import (
    HitlAction,
    HitlService,
    InMemoryHitlSignalStore,
)


def _exchange(body: Any = None, properties: dict[str, Any] | None = None) -> Exchange[Any]:
    return Exchange(
        in_message=Message(body=body, headers={}),
        properties=properties or {},
    )


def _context(route_id: str = "route-1") -> ExecutionContext:
    return ExecutionContext(route_id=route_id)


@pytest.mark.asyncio
async def test_approve_sets_hitl_approval_property() -> None:
    """Оператор approve → в properties попадает решение."""
    store = InMemoryHitlSignalStore()
    svc = HitlService(store=store)
    proc = HitlApprovalProcessor(
        hitl_service=svc,
        title="Approve transfer",
        timeout_seconds=5.0,
    )
    ex = _exchange(body={"amount": 1000})
    ctx = _context()

    async def _resolve_later() -> None:
        await asyncio.sleep(0.05)
        pending = await store.list_pending()
        assert len(pending) == 1
        await svc.resolve(
            signal_id=pending[0].signal_id,
            action=HitlAction.APPROVE,
            resolved_by="op@bank.local",
        )

    asyncio.create_task(_resolve_later())
    await proc.process(ex, ctx)

    assert ex.status != "failed"
    assert "hitl_approval" in ex.properties
    assert ex.properties["hitl_approval"]["action"] == "approved"
    assert ex.properties["hitl_approval"]["decided_by"] == "op@bank.local"


@pytest.mark.asyncio
async def test_reject_fails_exchange() -> None:
    """Оператор reject → exchange помечается failed."""
    store = InMemoryHitlSignalStore()
    svc = HitlService(store=store)
    proc = HitlApprovalProcessor(
        hitl_service=svc,
        title="Approve transfer",
        timeout_seconds=5.0,
    )
    ex = _exchange(body={"amount": 1000})
    ctx = _context()

    async def _reject_later() -> None:
        await asyncio.sleep(0.05)
        pending = await store.list_pending()
        await svc.resolve(
            signal_id=pending[0].signal_id,
            action=HitlAction.REJECT,
            resolved_by="op@bank.local",
        )

    asyncio.create_task(_reject_later())
    await proc.process(ex, ctx)

    assert ex.status == "failed"
    assert "rejected" in (ex.error or "")


@pytest.mark.asyncio
async def test_timeout_fails_exchange() -> None:
    """Решение не поступает вовремя → exchange failed по таймауту."""
    store = InMemoryHitlSignalStore()
    svc = HitlService(store=store)
    proc = HitlApprovalProcessor(
        hitl_service=svc,
        title="Approve transfer",
        timeout_seconds=0.05,
    )
    ex = _exchange(body={"amount": 1000})
    ctx = _context()

    await proc.process(ex, ctx)

    assert ex.status == "failed"
    assert "timeout" in (ex.error or "").lower()


@pytest.mark.asyncio
async def test_request_info_then_approve() -> None:
    """request_info → повторная регистрация → approve."""
    store = InMemoryHitlSignalStore()
    svc = HitlService(store=store)
    proc = HitlApprovalProcessor(
        hitl_service=svc,
        title="Approve transfer",
        timeout_seconds=5.0,
    )
    ex = _exchange(body={"amount": 1000})
    ctx = _context()

    async def _request_info_then_approve() -> None:
        await asyncio.sleep(0.05)
        pending = await store.list_pending()
        assert len(pending) == 1
        first_id = pending[0].signal_id
        await svc.resolve(
            signal_id=first_id,
            action=HitlAction.REQUEST_INFO,
            resolved_by="op@bank.local",
        )
        await asyncio.sleep(0.05)
        pending = await store.list_pending()
        # после request_info должен быть зарегистрирован новый signal
        assert len(pending) == 1
        second_id = pending[0].signal_id
        assert second_id != first_id
        await svc.resolve(
            signal_id=second_id,
            action=HitlAction.APPROVE,
            resolved_by="op@bank.local",
        )

    asyncio.create_task(_request_info_then_approve())
    await proc.process(ex, ctx)

    assert ex.status != "failed"
    assert ex.properties["hitl_approval"]["action"] == "approved_after_info_request"
