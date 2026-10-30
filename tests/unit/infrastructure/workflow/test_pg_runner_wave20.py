"""Wave 20 / ADR-0398 — PG-runner: пагинация event-log, sub_flow, for_each.

Дефекты проб ре-аудита:

1. [critical] Обрезка event-log на 1000 событий → повторное выполнение
   уже выполненных шагов (``read_events`` без пагинации по ``after_seq``).
2. [critical] ``sub_flow`` не порождает child и не завершает parent —
   workflow навсегда остаётся в ``running``, шаг переисполняется каждые
   30 с (backup-poll).
3. [high] ``for_each`` теряет результаты всех элементов кроме последнего.
"""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest

from src.backend.core.domain.models.workflow_event import WorkflowEventType
from src.backend.core.domain.models.workflow_instance import WorkflowStatus
from src.backend.infrastructure.workflow.executor import (
    DSLStepExecutor,
    WorkflowSpec,
    WorkflowStep,
)
from src.backend.infrastructure.workflow.pg_runner_internals import (
    WorkflowEventRow,
    WorkflowInstanceRow,
    WorkflowState,
)
from src.backend.infrastructure.workflow.runner import (
    DurableWorkflowRunner,
    RunnerConfig,
    StepOutcome,
)

# ── Fakes ───────────────────────────────────────────────────────────


class PagedEventStore:
    """In-memory event store, который честно режет страницы по ``limit``.

    Реальный ``WorkflowEventStore.read_events`` делает ``LIMIT :limit``
    в SQL. Фейк из wave-19 игнорировал ``limit`` и скрывал дефект
    пагинации — здесь limit соблюдается, как в PG.
    """

    def __init__(self) -> None:
        """Инициализация пустого log'а."""
        self.events: list[WorkflowEventRow] = []
        self._seq = 0

    async def append(
        self,
        workflow_id: UUID,
        event_type: WorkflowEventType,
        payload: dict[str, Any],
        step_name: str | None = None,
    ) -> int:
        """Дописать событие в лог, вернуть его ``seq``."""
        self._seq += 1
        self.events.append(
            WorkflowEventRow(
                seq=self._seq,
                workflow_id=workflow_id,
                event_type=event_type,
                payload=dict(payload),
                step_name=step_name,
                occurred_at=datetime.now(UTC),
            )
        )
        return self._seq

    async def read_events(
        self, workflow_id: UUID, after_seq: int = 0, limit: int = 1000
    ) -> list[WorkflowEventRow]:
        """Прочитать страницу событий ``seq > after_seq`` (как в PG: LIMIT)."""
        rows = [
            e for e in self.events if e.workflow_id == workflow_id and e.seq > after_seq
        ]
        return rows[:limit]

    async def snapshot(
        self, workflow_id: UUID, state: dict[str, Any], at_seq: int
    ) -> None:
        """Зафиксировать snapshot состояния событием ``snapshotted``."""
        await self.append(
            workflow_id,
            WorkflowEventType.snapshotted,
            {"at_seq": at_seq, "state": dict(state)},
            None,
        )


class FakeInstanceStore:
    """In-memory instance store (без PG) с lease-семантикой."""

    def __init__(self, instance: WorkflowInstanceRow) -> None:
        """Инициализация стора одним инстансом."""
        self.instance = instance
        self.statuses: list[WorkflowStatus] = []
        self.errors: list[str | None] = []
        self._lease_until: datetime | None = None
        self._lease_owner: str | None = None

    async def try_lock(self, workflow_id: UUID, worker_id: str, ttl_s: int) -> bool:
        """Взять lease, если её держит другой worker."""
        now = datetime.now(UTC)
        if self._lease_until is not None and self._lease_until > now:
            return False
        self._lease_until = now + timedelta(seconds=ttl_s)
        self._lease_owner = worker_id
        return True

    async def renew_lock(self, workflow_id: UUID, worker_id: str, ttl_s: int) -> bool:
        """Продлить lease, если он ещё наш."""
        if self._lease_owner != worker_id:
            return False
        self._lease_until = datetime.now(UTC) + timedelta(seconds=ttl_s)
        return True

    async def unlock(self, workflow_id: UUID, worker_id: str) -> None:
        """Отпустить lease."""
        if self._lease_owner == worker_id:
            self._lease_until = None
            self._lease_owner = None

    async def get(self, workflow_id: UUID) -> WorkflowInstanceRow | None:
        """Вернуть header инстанса."""
        return self.instance

    async def list_pending(
        self, limit: int = 100, tenant_id: str | None = None
    ) -> list[WorkflowInstanceRow]:
        """Pending-инстантов нет."""
        return []

    async def update_status(
        self,
        workflow_id: UUID,
        status: WorkflowStatus,
        next_attempt_at: datetime | None = None,
        error: str | None = None,
    ) -> None:
        """Обновить статус инстанса."""
        self.statuses.append(status)
        self.errors.append(error)
        self.instance = replace(self.instance, status=status)


def make_instance(
    workflow_id: UUID | None = None, status: WorkflowStatus = WorkflowStatus.running
) -> WorkflowInstanceRow:
    """Создать header-строку инстанса."""
    now = datetime.now(UTC)
    return WorkflowInstanceRow(
        id=workflow_id or uuid.uuid4(),
        workflow_name="wf-test",
        route_id="r-1",
        status=status,
        current_version=1,
        last_event_seq=None,
        snapshot_state=None,
        next_attempt_at=None,
        locked_by=None,
        locked_until=None,
        tenant_id="t-1",
        input_payload={},
        created_at=now,
        updated_at=now,
        finished_at=None,
    )


def body_of(payload: Any) -> dict[str, Any]:
    """Достать body из Exchange (или вернуть dict как есть)."""
    if hasattr(payload, "in_message"):
        raw = payload.in_message.body
        return dict(raw) if isinstance(raw, dict) else {}
    return dict(payload) if isinstance(payload, dict) else {}


def build_runner(
    *, executor: Any, instance: WorkflowInstanceRow
) -> tuple[DurableWorkflowRunner, FakeInstanceStore, PagedEventStore]:
    """Собрать runner с in-memory сторами."""
    store = FakeInstanceStore(instance)
    event_store = PagedEventStore()
    runner = DurableWorkflowRunner(
        config=RunnerConfig(worker_id="w-1"),
        executor=executor,
        state_store=store,  # type: ignore[arg-type]
        event_store=event_store,  # type: ignore[arg-type]
        listener_dsn=None,
    )
    return runner, store, event_store


# ── (1) Пагинация event-log ─────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_replay_reads_events_past_first_1000() -> None:
    """Runner обязан читать event-log постранично, а не только 1000 событий."""
    wf_id = uuid.uuid4()
    runner, _store, event_store = build_runner(
        executor=object(), instance=make_instance(wf_id)
    )
    for _ in range(2500):
        await event_store.append(
            wf_id, WorkflowEventType.signal_received, {"signal_name": "x"}, None
        )

    events = await runner._read_all_events(wf_id)

    assert len(events) == 2500
    assert events[-1].seq == 2500


@pytest.mark.unit
@pytest.mark.asyncio
async def test_more_than_1000_events_does_not_reexecute_completed_step() -> None:
    """Snapshot за первой тысячей событий не должен откатывать состояние.

    Регрессия: ``read_events`` отдавал только первые 1000 событий, replay
    не находил последний ``snapshotted`` и возвращался к старому
    состоянию — уже выполненный шаг исполнялся повторно (дубли эффектов).
    """
    wf_id = uuid.uuid4()
    calls: list[str] = []

    async def s1(payload: Any) -> dict[str, Any]:
        calls.append("s1")
        return body_of(payload)

    async def s2(payload: Any) -> dict[str, Any]:
        calls.append("s2")
        return body_of(payload)

    async def s3(payload: Any) -> dict[str, Any]:
        calls.append("s3")
        return body_of(payload)

    spec = WorkflowSpec(
        name="wf",
        steps=(
            WorkflowStep(kind="sequential", name="s1", processors=(s1,)),
            WorkflowStep(kind="sequential", name="s2", processors=(s2,)),
            WorkflowStep(kind="sequential", name="s3", processors=(s3,)),
        ),
    )
    executor = DSLStepExecutor(lambda _route_id: spec)
    runner, _store, event_store = build_runner(
        executor=executor, instance=make_instance(wf_id)
    )
    await event_store.append(
        wf_id,
        WorkflowEventType.created,
        {"workflow_name": "wf", "route_id": "r-1", "input": {}},
        None,
    )

    await runner._run_step(wf_id)
    # Шумовые события: последний snapshot уходит за пределы первой страницы.
    for _ in range(1200):
        await event_store.append(
            wf_id, WorkflowEventType.signal_received, {"signal_name": "noise"}, None
        )
    await runner._run_step(wf_id)
    await runner._run_step(wf_id)

    assert calls == ["s1", "s2", "s3"], "шаги не должны исполняться повторно"


# ── (2) sub_flow — fail-fast ────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_sub_flow_fails_fast_with_explicit_error() -> None:
    """sub_flow в pg-runner не поддерживается — понятная ошибка, не «висение»."""
    wf_id = uuid.uuid4()
    spec = WorkflowSpec(
        name="wf",
        steps=(
            WorkflowStep(
                kind="sub_flow",
                name="sub",
                workflow_name="child-wf",
                input_map={"x": "y"},
            ),
        ),
    )
    executor = DSLStepExecutor(lambda _route_id: spec)
    state = WorkflowState(workflow_id=wf_id)

    result = await executor.execute_next(instance=make_instance(wf_id), state=state)

    assert result.outcome == StepOutcome.FAILED
    assert "sub_flow" in (result.error_message or "")
    assert "pg-runner" in (result.error_message or "")
    assert not any(
        etype == WorkflowEventType.sub_spawned
        for etype, _payload, _name in result.events
    ), "sub_spawned больше не эмитится — child-workflow не создаётся"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_sub_flow_without_workflow_name_fails_fast() -> None:
    """Отсутствие workflow_name — тоже терминальный FAILED, а не pause."""
    wf_id = uuid.uuid4()
    spec = WorkflowSpec(name="wf", steps=(WorkflowStep(kind="sub_flow", name="sub"),))
    executor = DSLStepExecutor(lambda _route_id: spec)
    state = WorkflowState(workflow_id=wf_id)

    result = await executor.execute_next(instance=make_instance(wf_id), state=state)

    assert result.outcome == StepOutcome.FAILED
    reasons = [
        payload.get("reason")
        for etype, payload, _name in result.events
        if etype == WorkflowEventType.step_failed
    ]
    assert reasons == ["missing_workflow_name"]


# ── (3) for_each — per-item результаты ──────────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_for_each_collects_result_of_every_item() -> None:
    """for_each сохраняет результаты ВСЕХ элементов, а не только последнего."""
    wf_id = uuid.uuid4()

    async def proc(payload: Any) -> dict[str, Any]:
        body = body_of(payload)
        return {**body, "out": f"out-{body['current_item']}"}

    spec = WorkflowSpec(
        name="wf",
        steps=(
            WorkflowStep(
                kind="for_each",
                name="fe",
                collection_expr="items",
                body_steps=(
                    WorkflowStep(kind="sequential", name="inner", processors=(proc,)),
                ),
            ),
        ),
    )
    executor = DSLStepExecutor(lambda _route_id: spec)
    state = WorkflowState(workflow_id=wf_id)
    state.exchange_snapshot = {"items": [1, 2, 3]}

    result = await executor.execute_next(instance=make_instance(wf_id), state=state)

    finished = next(
        payload
        for etype, payload, _name in result.events
        if etype == WorkflowEventType.step_finished
    )
    exchange = finished["exchange"]
    per_item = exchange["for_each_results"]
    assert len(per_item) == 3
    assert [item["out"] for item in per_item] == ["out-1", "out-2", "out-3"]
    # Контракт ``out`` не сломан: последнее значение по-прежнему видно.
    assert exchange["out"] == "out-3"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_for_each_parallel_collects_result_of_every_item() -> None:
    """Parallel-ветка for_each тоже собирает per-item результаты."""
    wf_id = uuid.uuid4()

    async def proc(payload: Any) -> dict[str, Any]:
        body = body_of(payload)
        return {**body, "out": f"out-{body['current_item']}"}

    spec = WorkflowSpec(
        name="wf",
        steps=(
            WorkflowStep(
                kind="for_each",
                name="fe",
                collection_expr="items",
                parallel=True,
                body_steps=(
                    WorkflowStep(kind="sequential", name="inner", processors=(proc,)),
                ),
            ),
        ),
    )
    executor = DSLStepExecutor(lambda _route_id: spec)
    state = WorkflowState(workflow_id=wf_id)
    state.exchange_snapshot = {"items": [1, 2, 3]}

    result = await executor.execute_next(instance=make_instance(wf_id), state=state)

    finished = next(
        payload
        for etype, payload, _name in result.events
        if etype == WorkflowEventType.step_finished
    )
    per_item = finished["exchange"]["for_each_results"]
    assert sorted(item["out"] for item in per_item) == ["out-1", "out-2", "out-3"]


# ── (4) Retry-бюджет: admin-retry обнуляет attempts ─────────────────


@pytest.mark.unit
def test_resumed_event_with_attempts_reset_clears_retry_budget() -> None:
    """Событие retry обнуляет счётчик падений — иначе recover невозможен."""
    wf_id = uuid.uuid4()
    state = WorkflowState(workflow_id=wf_id)
    state.apply_event(
        WorkflowEventType.step_failed, {"error": "boom", "attempt": 11}, "s1"
    )
    assert state.attempts == 11

    state.apply_event(
        WorkflowEventType.resumed,
        {"reason": "admin_retry", "attempts_reset": True},
        None,
    )

    assert state.attempts == 0
