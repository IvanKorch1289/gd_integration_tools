"""Chaos: Saga double-fault сценарии (compensate падает во время компенсации).

Внешний план (позиция 4, «Saga double-fault chaos-test»): unit-suite
покрывает одиночный отказ компенсации; здесь проверяются **составные**
отказы на engine-Saga (``dsl/engine/processors/saga_lra.py``):

1. comp_B падает → компенсация comp_A всё равно выполняется (reverse-обход
   продолжается после ошибки);
2. state-store недоступен → in-memory fallback сохраняет те же инварианты;
3. CancelledError в компенсации **пробрасывается** (не глотается) —
   отмена должна оставаться отменой;
4. скрытых retry компенсации нет — ровно одна попытка;
5. audit-трейл фиксирует compensation_fail и итоговый compensation_fail;
6. persistent-путь сохраняет state="compensating" при double-fault.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange, ExchangeStatus, Message
from src.backend.dsl.engine.processors.base import BaseProcessor
from src.backend.dsl.engine.processors.control_flow import SagaStep
from src.backend.dsl.engine.processors.saga_lra import SagaLRAProcessor

pytestmark = pytest.mark.chaos


def _exchange() -> Exchange[Any]:
    msg = Message(body={}, headers={})
    return Exchange(in_message=msg, out_message=msg)


def _ctx() -> ExecutionContext:
    return ExecutionContext(route_id="chaos.saga")


class _FnProcessor(BaseProcessor):
    """Процессор-обёртка: пишет вызов в calls, может «упасть»."""

    def __init__(self, name: str, calls: list[str], *, fail: bool = False) -> None:
        super().__init__()
        self.name = name
        self._calls = calls
        self._fail = fail

    async def process(self, exchange: Exchange[Any], ctx: ExecutionContext) -> None:
        self._calls.append(self.name)
        if self._fail:
            exchange.fail(f"failed at {self.name}")


class _RaisingProcessor(BaseProcessor):
    """Процессор, который всегда бросает."""

    def __init__(self, name: str, calls: list[str], exc: BaseException) -> None:
        super().__init__()
        self.name = name
        self._calls = calls
        self._exc = exc

    async def process(self, exchange: Exchange[Any], ctx: ExecutionContext) -> None:
        self._calls.append(self.name)
        raise self._exc


def _make_saga(calls: list[str]) -> SagaLRAProcessor:
    """A(ok, comp ok) → B(ok, comp RAISES) → C(forward FAILS)."""
    return SagaLRAProcessor(
        steps=[
            SagaStep(
                forward=_FnProcessor("A", calls),
                compensate=_FnProcessor("comp_A", calls),
            ),
            SagaStep(
                forward=_FnProcessor("B", calls),
                compensate=_RaisingProcessor(
                    "comp_B", calls, RuntimeError("compensation failed at B")
                ),
            ),
            SagaStep(forward=_FnProcessor("C", calls, fail=True), compensate=None),
        ],
    )


def test_double_fault_continues_remaining_compensations() -> None:
    """comp_B упал → comp_A всё равно вызывается; exchange failed на шаге C."""
    calls: list[str] = []
    ex = _exchange()
    asyncio.run(_make_saga(calls).process(ex, _ctx()))

    assert ex.status == ExchangeStatus.failed
    assert "comp_B" in calls
    assert "comp_A" in calls
    assert calls.index("comp_B") < calls.index("comp_A")


def test_double_fault_state_and_properties() -> None:
    """После double-fault: failed-статус, failed_step=2, saga_error задан."""
    calls: list[str] = []
    ex = _exchange()
    asyncio.run(_make_saga(calls).process(ex, _ctx()))

    assert ex.get_property("saga_failed_step") == 2
    assert ex.get_property("saga_error")
    assert ex.get_property("saga_completed") is None


def test_state_store_down_in_memory_fallback_holds_invariants(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """State-store недоступен → in-memory fallback, инварианты double-fault те же."""
    calls: list[str] = []
    saga = _make_saga(calls)

    async def _repo_down() -> None:
        raise RuntimeError("state store down")

    monkeypatch.setattr(saga, "_get_repo", _repo_down)

    ex = _exchange()
    asyncio.run(saga.process(ex, _ctx()))
    assert ex.get_property("saga_failed_step") == 2
    assert "comp_B" in calls and "comp_A" in calls


@pytest.mark.asyncio
async def test_cancelled_error_in_compensation_propagates() -> None:
    """CancelledError в компенсации пробрасывается — отмена не глотается."""
    calls: list[str] = []
    saga = SagaLRAProcessor(
        steps=[
            SagaStep(
                forward=_FnProcessor("A", calls),
                compensate=_RaisingProcessor("comp_A", calls, asyncio.CancelledError()),
            ),
            SagaStep(forward=_FnProcessor("B", calls, fail=True), compensate=None),
        ],
    )
    with pytest.raises(asyncio.CancelledError):
        await saga.process(_exchange(), _ctx())


@pytest.mark.asyncio
async def test_no_hidden_retry_in_compensation() -> None:
    """Упавшая компенсация вызывается ровно один раз — скрытого retry нет."""
    calls: list[str] = []
    ex = _exchange()
    await _make_saga(calls).process(ex, _ctx())
    assert calls.count("comp_B") == 1


@pytest.mark.asyncio
async def test_audit_trail_on_double_fault() -> None:
    """Audit: compensation_fail для падшей компенсации, итоговый — тоже fail."""
    calls: list[str] = []
    events: list[dict[str, Any]] = []
    ex = _exchange()

    async def _capture(**kwargs: Any) -> None:
        events.append(kwargs)

    saga = _make_saga(calls)
    with patch(
        "src.backend.dsl.engine.processors.saga_lra._emit_saga_audit",
        side_effect=_capture,
    ):
        await saga.process(ex, _ctx())

    names = [e["event_type"] for e in events]
    assert "workflow.compensation_fail" in names
    assert "workflow.compensation_complete" not in names
    assert "workflow.compensation_start" in names


@pytest.mark.asyncio
async def test_persistent_double_fault_persists_compensating_state() -> None:
    """Persistent: при double-fault сохраняется state='compensating'."""
    calls: list[str] = []
    repo = MagicMock()
    repo.load = AsyncMock(return_value=None)
    # save() возвращает state-record (используется далее как state_record).
    state_record = MagicMock(state="running", step_index=0)
    repo.save = AsyncMock(return_value=state_record)

    saga = _make_saga(calls)
    saga._get_repo = AsyncMock(return_value=repo)  # type: ignore[method-assign]

    ex = _exchange()
    await saga.process(ex, _ctx())

    saved_states = [
        c.kwargs.get("state") for c in repo.save.await_args_list if "state" in c.kwargs
    ]
    assert "compensating" in saved_states
    assert "running" in saved_states
