"""Focused tests: SensorProcessor (Airflow poke/reschedule, MINIMAX W10).

Покрытие:
1. poke: ready → pass, не-ready → exchange.fail (одна проверка).
2. reschedule: условие становится ready → pass; never-ready → timeout fail.
3. DeadlineBudget (ADR-0305): admission control на входе (0 проверок),
   narrowing timeout до remaining, graceful degradation без RequestContext.
4. Безопасный дефолт: reschedule без timeout/budget → одна проверка.
5. Валидация конструктора (mode/interval) + to_spec.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from src.backend.core.async_utils.deadline_budget import DeadlineBudget
from src.backend.core.request_context import (
    RequestContext,
    bind_request_context,
    clear_request_context,
)
from src.backend.dsl.engine.exchange import Exchange, ExchangeStatus, Message
from src.backend.dsl.engine.processors.eip.flow_control import SensorProcessor


def _ex(body: Any = None) -> Exchange[Any]:
    return Exchange(in_message=Message(body=body))


def _ctx() -> AsyncMock:
    return AsyncMock()


# --- poke mode ------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_poke_ready_passes() -> None:
    """poke: predicate True → exchange не провален, одна проверка."""
    calls: list[int] = []

    def pred(exchange: Exchange[Any]) -> bool:
        calls.append(1)
        return True

    proc = SensorProcessor(pred)
    e = _ex()
    await proc.process(e, _ctx())
    assert e.status != ExchangeStatus.failed
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_poke_not_ready_fails() -> None:
    """poke: predicate False → exchange.fail, статус failed."""
    proc = SensorProcessor(lambda ex: False)
    e = _ex()
    await proc.process(e, _ctx())
    assert e.status == ExchangeStatus.failed
    assert "not ready" in (e.error or "")


# --- reschedule mode -------------------------------------------------------- #


@pytest.mark.asyncio
async def test_reschedule_becomes_ready() -> None:
    """reschedule: условие выполняется на 2-й проверке → pass."""
    state = {"n": 0}

    def pred(exchange: Exchange[Any]) -> bool:
        state["n"] += 1
        return state["n"] >= 2

    proc = SensorProcessor(pred, mode="reschedule", interval_s=0.01, timeout_s=5.0)
    e = _ex()
    await proc.process(e, _ctx())
    assert state["n"] == 2
    assert e.status != ExchangeStatus.failed


@pytest.mark.asyncio
async def test_reschedule_timeout_fail() -> None:
    """reschedule: условие никогда не ready → fail по timeout."""
    calls: list[int] = []
    proc = SensorProcessor(
        lambda ex: calls.append(1) or False,
        mode="reschedule",
        interval_s=0.01,
        timeout_s=0.05,
    )
    e = _ex()
    await proc.process(e, _ctx())
    assert e.status == ExchangeStatus.failed
    assert "Sensor timeout" in (e.error or "")
    assert len(calls) >= 2  # поллинг был, не одна проверка


@pytest.mark.asyncio
async def test_reschedule_no_timeout_single_check_fallback() -> None:
    """reschedule без timeout_s и без budget → одна проверка (анти-infinite-loop)."""
    calls: list[int] = []
    proc = SensorProcessor(
        lambda ex: calls.append(1) or False,
        mode="reschedule",
        interval_s=0.01,
        timeout_s=None,
    )
    e = _ex()
    await proc.process(e, _ctx())
    assert len(calls) == 1
    assert e.status == ExchangeStatus.failed


# --- deadline budget (ADR-0305) --------------------------------------------- #


@pytest.mark.asyncio
async def test_budget_expired_admission_control() -> None:
    """Budget истёк на входе → fail без единой проверки predicate."""
    import asyncio

    calls: list[int] = []
    proc = SensorProcessor(
        lambda ex: calls.append(1) or True,
        mode="reschedule",
        interval_s=0.01,
        timeout_s=5.0,
    )
    budget = DeadlineBudget.from_timeout(timeout=0.001)
    await asyncio.sleep(0.005)  # budget естественно истекает

    e = _ex()
    ctx = RequestContext(
        correlation_id="c",
        request_id="r",
        method="GET",
        path="/",
        deadline_budget=budget,
    )
    token = bind_request_context(ctx)
    try:
        await proc.process(e, _ctx())
    finally:
        clear_request_context(token)
    assert calls == []
    assert e.status == ExchangeStatus.failed
    assert "deadline budget exhausted" in (e.error or "")


@pytest.mark.asyncio
async def test_budget_narrows_timeout() -> None:
    """Budget remaining < timeout_s → reschedule ограничен бюджетом (fail быстрее)."""
    calls: list[int] = []
    proc = SensorProcessor(
        lambda ex: calls.append(1) or False,
        mode="reschedule",
        interval_s=0.02,
        timeout_s=60.0,
    )
    budget = DeadlineBudget.from_timeout(timeout=0.05)
    e = _ex()
    ctx = RequestContext(
        correlation_id="c",
        request_id="r",
        method="GET",
        path="/",
        deadline_budget=budget,
    )
    token = bind_request_context(ctx)
    try:
        await proc.process(e, _ctx())
    finally:
        clear_request_context(token)
    assert e.status == ExchangeStatus.failed
    assert len(calls) < 10  # не ждал 60s — budget сузил до ~0.05s


# --- constructor validation + spec ------------------------------------------- #


def test_invalid_mode_raises() -> None:
    """Неизвестный mode → ValueError."""
    with pytest.raises(ValueError, match="mode"):
        SensorProcessor(lambda ex: True, mode="spin")


def test_invalid_interval_raises() -> None:
    """interval_s <= 0 → ValueError."""
    with pytest.raises(ValueError, match="interval_s"):
        SensorProcessor(lambda ex: True, mode="reschedule", interval_s=0)


def test_to_spec_serializes_params() -> None:
    """to_spec отдаёт mode/interval/timeout; predicate не сериализуется."""
    proc = SensorProcessor(
        lambda ex: True, mode="reschedule", interval_s=2.0, timeout_s=30.0
    )
    spec = proc.to_spec()
    assert spec == {
        "sensor": {"mode": "reschedule", "interval_s": 2.0, "timeout_s": 30.0}
    }
