"""Wave 19 / ADR-0394 — ядро PG-runner: данные, FAILED, отмена, branch, wait, lease.

Тесты кластера A (дефекты проб ревью):

1. Потеря данных между этапами (``exchange`` payload + snapshot).
2. Падение этапа никогда не даёт FAILED (attempts / max_attempts).
3. Отмена не работает (``cancelling`` → ``cancelled``).
4. Branch-шаг зацикливается (нет ``step_finished``).
5. Wait-шаг не завершается (нет дедлайна в состоянии).
6. CONTINUE-reenqueue теряется (id в ``_active_executions``).
7. Lease-лок не защищает от двойного исполнения (``rowcount`` игнорируется).
8. Lease не продлевается (TTL < timeout шага) — нужен heartbeat.
"""

from __future__ import annotations

import asyncio
import hashlib
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
    WorkflowInstanceStore,
    WorkflowState,
)
from src.backend.infrastructure.workflow.runner import (
    DurableWorkflowRunner,
    RunnerConfig,
    StepOutcome,
    StepResult,
)

# ── Fakes ───────────────────────────────────────────────────────────


class FakeInstanceStore:
    """In-memory instance store (без PG) с lease-семантикой.

    ``try_lock`` возвращает ``False``, если lease держит другой worker' —
    так же, как ``UPDATE ... WHERE locked_until < now`` в PG.
    """

    def __init__(self, instance: WorkflowInstanceRow) -> None:
        self.instance = instance
        self.statuses: list[WorkflowStatus] = []
        self.errors: list[str | None] = []
        self.lock_calls = 0
        self.renew_calls = 0
        self.unlock_calls = 0
        self._lease_until: datetime | None = None
        self._lease_owner: str | None = None

    async def try_lock(self, workflow_id: UUID, worker_id: str, ttl_s: int) -> bool:
        self.lock_calls += 1
        now = datetime.now(UTC)
        if self._lease_until is not None and self._lease_until > now:
            return False
        self._lease_until = now + timedelta(seconds=ttl_s)
        self._lease_owner = worker_id
        return True

    async def renew_lock(self, workflow_id: UUID, worker_id: str, ttl_s: int) -> bool:
        self.renew_calls += 1
        now = datetime.now(UTC)
        if self._lease_owner != worker_id or (
            self._lease_until is not None and self._lease_until <= now
        ):
            return False
        self._lease_until = now + timedelta(seconds=ttl_s)
        return True

    async def unlock(self, workflow_id: UUID, worker_id: str) -> None:
        self.unlock_calls += 1
        # Небольшая задержка расширяет окно, в котором re-enqueue ещё
        # виден диспетчеру как «дубликат активной execution'и».
        await asyncio.sleep(0.02)
        if self._lease_owner == worker_id:
            self._lease_until = None
            self._lease_owner = None

    async def get(self, workflow_id: UUID) -> WorkflowInstanceRow | None:
        return self.instance

    async def list_pending(
        self, limit: int = 100, tenant_id: str | None = None
    ) -> list[WorkflowInstanceRow]:
        return []

    async def update_status(
        self,
        workflow_id: UUID,
        status: WorkflowStatus,
        next_attempt_at: datetime | None = None,
        error: str | None = None,
    ) -> None:
        self.statuses.append(status)
        self.errors.append(error)
        finished_at = (
            datetime.now(UTC)
            if status
            in {
                WorkflowStatus.succeeded,
                WorkflowStatus.failed,
                WorkflowStatus.cancelled,
            }
            else None
        )
        self.instance = replace(self.instance, status=status, finished_at=finished_at)


class FakeEventStore:
    """In-memory append-only event store."""

    def __init__(self) -> None:
        self.events: list[WorkflowEventRow] = []
        self.snapshots: list[dict[str, Any]] = []
        self._seq = 0

    async def append(
        self,
        workflow_id: UUID,
        event_type: WorkflowEventType,
        payload: dict[str, Any],
        step_name: str | None = None,
    ) -> int:
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
        return [e for e in self.events if e.seq > after_seq]

    async def snapshot(
        self, workflow_id: UUID, state: dict[str, Any], at_seq: int
    ) -> None:
        """Фиксирует snapshot состояния (как реальный event store)."""
        self.snapshots.append(dict(state))
        await self.append(
            workflow_id,
            WorkflowEventType.snapshotted,
            {"at_seq": at_seq, "state": dict(state)},
            None,
        )


def make_instance(
    workflow_id: UUID | None = None, status: WorkflowStatus = WorkflowStatus.running
) -> WorkflowInstanceRow:
    """Создаёт header-строку инстанса."""
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


def created_event(
    workflow_id: UUID, payload: dict[str, Any] | None = None
) -> WorkflowEventRow:
    """Создаёт событие ``created``."""
    return WorkflowEventRow(
        seq=1,
        workflow_id=workflow_id,
        event_type=WorkflowEventType.created,
        payload=payload
        if payload is not None
        else {"workflow_name": "wf-test", "route_id": "r-1", "input": {}},
        step_name=None,
        occurred_at=datetime.now(UTC),
    )


def body_of(payload: Any) -> dict[str, Any]:
    """Достаёт body из Exchange (или возвращает dict как есть)."""
    if hasattr(payload, "in_message"):
        raw = payload.in_message.body
        return dict(raw) if isinstance(raw, dict) else {}
    return dict(payload) if isinstance(payload, dict) else {}


def build_runner(
    *, executor: Any, instance: WorkflowInstanceRow, config: RunnerConfig | None = None
) -> tuple[
    DurableWorkflowRunner, FakeInstanceStore, FakeEventStore, WorkflowInstanceRow
]:
    """Собирает runner с in-memory сторами."""
    store = FakeInstanceStore(instance)
    event_store = FakeEventStore()
    runner = DurableWorkflowRunner(
        config=config or RunnerConfig(worker_id="w-1"),
        executor=executor,
        state_store=store,  # type: ignore[arg-type]
        event_store=event_store,  # type: ignore[arg-type]
        listener_dsn=None,
    )
    return runner, store, event_store, instance


# ── (1) Данные между шагами ─────────────────────────────────────────


@pytest.mark.unit
def test_created_event_seeds_exchange_snapshot() -> None:
    """``created`` должен класть вход workflow'а в exchange_snapshot."""
    wf_id = uuid.uuid4()
    events = [created_event(wf_id, {"workflow_name": "wf", "input": {"seed": 7}})]

    state = WorkflowState.replay(events)

    assert state.exchange_snapshot == {"seed": 7}


@pytest.mark.unit
def test_created_event_ignores_internal_metadata_keys() -> None:
    """Служебные ``__``-ключи не должны попадать в exchange."""
    wf_id = uuid.uuid4()
    events = [
        created_event(
            wf_id,
            {"workflow_name": "wf", "input": {"seed": 7, "__workflow_id": "wf-42"}},
        )
    ]

    state = WorkflowState.replay(events)

    assert state.exchange_snapshot == {"seed": 7}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_step_finished_uses_exchange_payload_key() -> None:
    """Единый контракт: результат шага едет в payload под ключом ``exchange``."""
    seen: list[dict[str, Any]] = []

    async def proc(payload: Any) -> dict[str, Any]:
        seen.append(body_of(payload))
        return {**body_of(payload), "value": 42}

    wf_id = uuid.uuid4()
    spec = WorkflowSpec(
        name="wf",
        steps=(WorkflowStep(kind="sequential", name="s1", processors=(proc,)),),
    )
    executor = DSLStepExecutor(lambda _route_id: spec)
    state = WorkflowState(workflow_id=wf_id)
    state.exchange_snapshot = {"seed": 7}

    result = await executor.execute_next(instance=make_instance(wf_id), state=state)

    payloads = {etype: payload for etype, payload, _ in result.events}
    assert WorkflowEventType.step_finished in payloads
    assert "exchange" in payloads[WorkflowEventType.step_finished]
    assert "output" not in payloads[WorkflowEventType.step_finished]
    assert payloads[WorkflowEventType.step_finished]["exchange"] == {
        "seed": 7,
        "value": 42,
    }
    assert seen == [{"seed": 7}]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_step_output_visible_to_next_step() -> None:
    """Выход шага 1 должен быть виден шагу 2 (сквозной runner)."""
    seen_by_step2: list[dict[str, Any]] = []

    async def step1(payload: Any) -> dict[str, Any]:
        body = body_of(payload)
        return {**body, "value": body["seed"] * 6}

    async def step2(payload: Any) -> dict[str, Any]:
        seen_by_step2.append(body_of(payload))
        return body_of(payload)

    wf_id = uuid.uuid4()
    spec = WorkflowSpec(
        name="wf",
        steps=(
            WorkflowStep(kind="sequential", name="s1", processors=(step1,)),
            WorkflowStep(kind="sequential", name="s2", processors=(step2,)),
        ),
    )
    executor = DSLStepExecutor(lambda _route_id: spec)
    instance = make_instance(wf_id)
    runner, _store, event_store, _instance = build_runner(
        executor=executor, instance=instance
    )
    await event_store.append(
        wf_id,
        WorkflowEventType.created,
        {"workflow_name": "wf", "route_id": "r-1", "input": {"seed": 7}},
        None,
    )

    await runner._run_step(wf_id)
    await runner._run_step(wf_id)

    assert seen_by_step2 == [{"seed": 7, "value": 42}]
    replayed = WorkflowState.replay(event_store.events)
    assert replayed.exchange_snapshot == {"seed": 7, "value": 42}
    assert replayed.current_step == 2


@pytest.mark.unit
@pytest.mark.asyncio
async def test_runner_persists_output_state_snapshot() -> None:
    """Runner сохраняет ``StepResult.output_state`` в snapshot инстанса."""

    async def proc(payload: Any) -> dict[str, Any]:
        return {**body_of(payload), "value": 1}

    wf_id = uuid.uuid4()
    spec = WorkflowSpec(
        name="wf",
        steps=(WorkflowStep(kind="sequential", name="s1", processors=(proc,)),),
    )
    executor = DSLStepExecutor(lambda _route_id: spec)
    instance = make_instance(wf_id)
    runner, store, event_store, _instance = build_runner(
        executor=executor, instance=instance
    )
    await event_store.append(
        wf_id,
        WorkflowEventType.created,
        {"workflow_name": "wf", "route_id": "r-1", "input": {"seed": 7}},
        None,
    )

    await runner._run_step(wf_id)

    assert event_store.snapshots, "runner должен сохранять snapshot состояния"
    assert event_store.snapshots[-1]["exchange_snapshot"] == {"seed": 7, "value": 1}


# ── (2) FAILED после max_attempts ──────────────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_failed_step_counts_attempts_and_reaches_failed() -> None:
    """attempts растут; на ``max_attempts`` — FAILED, а не бесконечный PAUSE."""
    wf_id = uuid.uuid4()

    async def boom(payload: Any) -> dict[str, Any]:
        raise RuntimeError("kaboom")

    spec = WorkflowSpec(
        name="wf",
        steps=(WorkflowStep(kind="sequential", name="s1", processors=(boom,)),),
        max_attempts=3,
    )
    executor = DSLStepExecutor(lambda _route_id: spec)
    state = WorkflowState(workflow_id=wf_id)
    instance = make_instance(wf_id)

    outcomes: list[str] = []
    failed_payloads: list[dict[str, Any]] = []
    for _ in range(3):
        result = await executor.execute_next(instance=instance, state=state)
        outcomes.append(result.outcome)
        for etype, payload, step_name in result.events:
            state.apply_event(etype, payload, step_name)
            if etype == WorkflowEventType.step_failed:
                failed_payloads.append(payload)

    assert outcomes == [StepOutcome.PAUSE, StepOutcome.PAUSE, StepOutcome.FAILED]
    assert state.attempts == 3
    assert failed_payloads[-1]["attempt"] == 3
    assert failed_payloads[-1]["reason"] == "max_attempts_exceeded"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_runner_transitions_to_failed_when_attempts_exhausted() -> None:
    """Runner переводит инстанс в FAILED, когда retry-бюджет исчерпан."""
    wf_id = uuid.uuid4()

    async def boom(payload: Any) -> dict[str, Any]:
        raise RuntimeError("kaboom")

    spec = WorkflowSpec(
        name="wf",
        steps=(WorkflowStep(kind="sequential", name="s1", processors=(boom,)),),
        max_attempts=2,
    )
    executor = DSLStepExecutor(lambda _route_id: spec)
    instance = make_instance(wf_id)
    runner, store, event_store, _instance = build_runner(
        executor=executor, instance=instance
    )
    await event_store.append(
        wf_id,
        WorkflowEventType.created,
        {"workflow_name": "wf", "route_id": "r-1", "input": {}},
        None,
    )

    await runner._run_step(wf_id)
    await runner._run_step(wf_id)

    assert WorkflowStatus.failed in store.statuses
    assert store.errors[-1]


# ── (3) Отмена ──────────────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_cancelling_instance_is_cancelled_without_executing_steps() -> None:
    """``cancelling`` → ``cancelled`` (событие + finished_at), шаги не выполняются."""
    wf_id = uuid.uuid4()
    calls: list[int] = []

    class _Executor:
        async def execute_next(
            self, *, instance: WorkflowInstanceRow, state: WorkflowState
        ) -> StepResult:
            calls.append(1)
            return StepResult(outcome=StepOutcome.CONTINUE)

    instance = make_instance(wf_id, status=WorkflowStatus.cancelling)
    runner, store, event_store, _instance = build_runner(
        executor=_Executor(), instance=instance
    )
    await event_store.append(
        wf_id,
        WorkflowEventType.created,
        {"workflow_name": "wf", "route_id": "r-1", "input": {}},
        None,
    )

    await runner._run_step(wf_id)

    assert calls == []
    assert any(e.event_type == WorkflowEventType.cancelled for e in event_store.events)
    assert store.statuses == [WorkflowStatus.cancelled]
    assert store.instance.finished_at is not None


# ── (4) Branch ──────────────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_branch_step_advances_cursor() -> None:
    """Branch обязан эмитить ``step_finished`` — иначе курсор зацикливается."""
    wf_id = uuid.uuid4()

    async def proc(payload: Any) -> dict[str, Any]:
        return {**body_of(payload), "branch": "done"}

    spec = WorkflowSpec(
        name="wf",
        steps=(
            WorkflowStep(
                kind="branch",
                name="b1",
                predicate=lambda _state: True,
                then_steps=(
                    WorkflowStep(kind="sequential", name="inner", processors=(proc,)),
                ),
            ),
            WorkflowStep(kind="sequential", name="s2", processors=(proc,)),
        ),
    )
    executor = DSLStepExecutor(lambda _route_id: spec)
    state = WorkflowState(workflow_id=wf_id)
    instance = make_instance(wf_id)

    result = await executor.execute_next(instance=instance, state=state)
    for etype, payload, step_name in result.events:
        state.apply_event(etype, payload, step_name)

    assert any(
        etype == WorkflowEventType.step_finished for etype, _, _ in result.events
    )
    assert state.current_step == 1
    assert state.exchange_snapshot == {"branch": "done"}


# ── (5) Wait ────────────────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_wait_step_completes_after_deadline() -> None:
    """Wait-шаг фиксирует дедлайн в состоянии и по его достижении завершается."""
    wf_id = uuid.uuid4()
    spec = WorkflowSpec(
        name="wf",
        steps=(
            WorkflowStep(kind="wait", name="w1", duration_s=0.0),
            WorkflowStep(kind="sequential", name="s2", processors=()),
        ),
    )
    executor = DSLStepExecutor(lambda _route_id: spec)
    state = WorkflowState(workflow_id=wf_id)
    instance = make_instance(wf_id)

    first = await executor.execute_next(instance=instance, state=state)
    for etype, payload, step_name in first.events:
        state.apply_event(etype, payload, step_name)

    assert first.outcome == StepOutcome.PAUSE
    assert "w1" in state.wait_deadlines

    second = await executor.execute_next(instance=instance, state=state)
    for etype, payload, step_name in second.events:
        state.apply_event(etype, payload, step_name)

    assert second.outcome == StepOutcome.CONTINUE
    assert any(
        etype == WorkflowEventType.step_finished for etype, _, _ in second.events
    )
    assert state.current_step == 1


# ── (6) CONTINUE-reenqueue ──────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_continue_outcome_leaves_active_set_before_reenqueue() -> None:
    """id должен быть убран из ``_active_executions`` ДО re-enqueue."""
    wf_id = uuid.uuid4()
    runner, _store, _events, instance = build_runner(
        executor=object(), instance=make_instance(wf_id)
    )
    runner._active_executions.add(wf_id)

    await runner._apply_outcome(
        wf_id,
        StepResult(outcome=StepOutcome.CONTINUE),
        WorkflowState(workflow_id=wf_id),
        instance,
    )

    assert wf_id not in runner._active_executions
    assert runner._pending_instance_ids.get_nowait() == wf_id


@pytest.mark.unit
@pytest.mark.asyncio
async def test_dispatch_loop_executes_reenqueued_workflow() -> None:
    """Re-enqueue после CONTINUE не теряется: следующий шаг выполняется."""
    wf_id = uuid.uuid4()
    calls: list[int] = []

    class _Executor:
        async def execute_next(
            self, *, instance: WorkflowInstanceRow, state: WorkflowState
        ) -> StepResult:
            calls.append(1)
            if len(calls) >= 2:
                return StepResult(outcome=StepOutcome.DONE)
            return StepResult(outcome=StepOutcome.CONTINUE)

    runner, _store, event_store, _instance = build_runner(
        executor=_Executor(), instance=make_instance(wf_id)
    )
    await event_store.append(
        wf_id,
        WorkflowEventType.created,
        {"workflow_name": "wf", "route_id": "r-1", "input": {}},
        None,
    )
    runner._running = True
    dispatch = asyncio.create_task(runner._dispatch_loop())
    try:
        runner._pending_instance_ids.put_nowait(wf_id)
        for _ in range(100):
            if len(calls) >= 2:
                break
            await asyncio.sleep(0.01)
    finally:
        runner._running = False
        dispatch.cancel()
        with pytest.raises(asyncio.CancelledError):
            await dispatch

    assert len(calls) == 2


# ── (7) Lease: rowcount ─────────────────────────────────────────────


class _FakeResult:
    """Минимальный результат execute() с rowcount."""

    def __init__(self, scalar: Any = None, rowcount: int = 0) -> None:
        self._scalar = scalar
        self.rowcount = rowcount

    def scalar(self) -> Any:
        """Возвращает scalar-значение результата."""
        return self._scalar


class _FakeSession:
    """Минимальная async-сессия SQLAlchemy."""

    def __init__(self, results: list[_FakeResult]) -> None:
        self._results = list(results)
        self.executed: list[Any] = []

    async def execute(self, stmt: Any, params: Any = None) -> _FakeResult:
        """Возвращает заранее подготовленный результат."""
        self.executed.append(stmt)
        if not self._results:
            return _FakeResult()
        return self._results.pop(0)

    async def flush(self) -> None:
        """No-op flush."""

    def add(self, obj: Any) -> None:
        """No-op add."""


class _AsyncCtx:
    """Async context manager поверх готового объекта."""

    def __init__(self, value: Any) -> None:
        self._value = value

    async def __aenter__(self) -> Any:
        """Возвращает объект."""
        return self._value

    async def __aexit__(self, *exc: Any) -> bool:
        """Всегда подавляет исключения."""
        return False


class _FakeSessionManager:
    """Минимальный session manager для store."""

    def __init__(self, session: _FakeSession) -> None:
        self.session = session

    def create_session(self) -> _AsyncCtx:
        """Возвращает async CM с сессией."""
        return _AsyncCtx(self.session)

    def transaction(self, session: Any) -> _AsyncCtx:
        """Возвращает async CM транзакции."""
        return _AsyncCtx(session)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_try_lock_returns_false_when_lease_update_affects_no_rows() -> None:
    """UPDATE lease не обновил ни одной строки → lock не получен."""
    wf_id = uuid.uuid4()
    session = _FakeSession([_FakeResult(scalar=True), _FakeResult(rowcount=0)])
    store = WorkflowInstanceStore(session_manager=_FakeSessionManager(session))

    assert await store.try_lock(wf_id, "w-1", 120) is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_try_lock_returns_true_when_lease_updated() -> None:
    """UPDATE lease обновил строку → lock получен."""
    wf_id = uuid.uuid4()
    session = _FakeSession([_FakeResult(scalar=True), _FakeResult(rowcount=1)])
    store = WorkflowInstanceStore(session_manager=_FakeSessionManager(session))

    assert await store.try_lock(wf_id, "w-1", 120) is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_renew_lock_returns_false_when_lease_lost() -> None:
    """Heartbeat не продлевает чужой lease."""
    wf_id = uuid.uuid4()
    session = _FakeSession([_FakeResult(rowcount=0)])
    store = WorkflowInstanceStore(session_manager=_FakeSessionManager(session))

    assert await store.renew_lock(wf_id, "w-1", 120) is False


# ── (8) Lease heartbeat ─────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_heartbeat_renews_lease_during_long_step() -> None:
    """Долгий шаг продлевает lease (TTL меньше таймаута шага)."""
    wf_id = uuid.uuid4()

    async def slow(payload: Any) -> dict[str, Any]:
        await asyncio.sleep(0.5)
        return body_of(payload)

    spec = WorkflowSpec(
        name="wf",
        steps=(WorkflowStep(kind="sequential", name="s1", processors=(slow,)),),
    )
    executor = DSLStepExecutor(lambda _route_id: spec)
    instance = make_instance(wf_id)
    runner, store, event_store, _instance = build_runner(
        executor=executor,
        instance=instance,
        config=RunnerConfig(worker_id="w-1", lock_ttl_s=1),
    )
    await event_store.append(
        wf_id,
        WorkflowEventType.created,
        {"workflow_name": "wf", "route_id": "r-1", "input": {}},
        None,
    )

    await runner._run_step(wf_id)

    assert store.renew_calls >= 1


# ── (9) Идемпотентность ретраев/рестарта ────────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_step_started_written_before_step_execution() -> None:
    """``step_started`` пишется ДО выполнения шага.

    Иначе падение между эффектом шага и append'ом события приводит к
    повторному исполнению шага при resume (ADR-0394).
    """
    wf_id = uuid.uuid4()
    observed: list[str] = []

    async def proc(payload: Any) -> dict[str, Any]:
        # Последнее событие в логе на момент исполнения процессора.
        observed.append(
            event_store.events[-1].event_type.value if event_store.events else ""
        )
        return body_of(payload)

    spec = WorkflowSpec(
        name="wf",
        steps=(WorkflowStep(kind="sequential", name="s1", processors=(proc,)),),
    )
    executor = DSLStepExecutor(lambda _route_id: spec)
    instance = make_instance(wf_id)
    runner, _store, event_store, _instance = build_runner(
        executor=executor, instance=instance
    )
    await event_store.append(
        wf_id,
        WorkflowEventType.created,
        {"workflow_name": "wf", "route_id": "r-1", "input": {}},
        None,
    )

    await runner._run_step(wf_id)

    assert observed == ["step_started"]
    # Порядок событий: created → step_started → step_finished → snapshotted.
    assert [e.event_type.value for e in event_store.events] == [
        "created",
        "step_started",
        "step_finished",
        "snapshotted",
    ]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_step_events_carry_deterministic_idempotency_key() -> None:
    """``step_started``/``step_finished`` несут idempotency-key шага."""
    wf_id = uuid.uuid4()

    async def proc(payload: Any) -> dict[str, Any]:
        return body_of(payload)

    spec = WorkflowSpec(
        name="wf",
        steps=(WorkflowStep(kind="sequential", name="s1", processors=(proc,)),),
    )
    executor = DSLStepExecutor(lambda _route_id: spec)
    instance = make_instance(wf_id)
    runner, _store, event_store, _instance = build_runner(
        executor=executor, instance=instance
    )
    await event_store.append(
        wf_id,
        WorkflowEventType.created,
        {"workflow_name": "wf", "route_id": "r-1", "input": {}},
        None,
    )

    await runner._run_step(wf_id)

    started = [
        e for e in event_store.events if e.event_type == WorkflowEventType.step_started
    ]
    finished = [
        e for e in event_store.events if e.event_type == WorkflowEventType.step_finished
    ]
    assert len(started) == 1, "step_started должен писаться ровно один раз"
    assert started[0].step_name == "s1"
    attempt = started[0].payload["attempt"]
    expected = hashlib.sha256(f"{wf_id}|s1|{attempt}".encode()).hexdigest()
    assert started[0].payload["idempotency_key"] == expected
    assert finished[0].payload["idempotency_key"] == expected


# ── (10) Snapshot состояния ─────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_runner_writes_snapshot_after_events() -> None:
    """После шага пишется snapshot (событие ``snapshotted`` + payload state)."""
    wf_id = uuid.uuid4()

    async def proc(payload: Any) -> dict[str, Any]:
        return {**body_of(payload), "value": 1}

    spec = WorkflowSpec(
        name="wf",
        steps=(WorkflowStep(kind="sequential", name="s1", processors=(proc,)),),
    )
    executor = DSLStepExecutor(lambda _route_id: spec)
    instance = make_instance(wf_id)
    runner, store, event_store, _instance = build_runner(
        executor=executor, instance=instance
    )
    await event_store.append(
        wf_id,
        WorkflowEventType.created,
        {"workflow_name": "wf", "route_id": "r-1", "input": {"seed": 7}},
        None,
    )

    await runner._run_step(wf_id)

    snapshots = [
        e for e in event_store.events if e.event_type == WorkflowEventType.snapshotted
    ]
    assert len(snapshots) == 1, "runner должен писать snapshot состояния"
    state_payload = snapshots[0].payload["state"]
    assert state_payload["exchange_snapshot"] == {"seed": 7, "value": 1}
    assert state_payload["current_step"] == 1
    # Replay из snapshot'а восстанавливает тот же state.
    replayed = WorkflowState.replay(event_store.events)
    assert replayed.exchange_snapshot == {"seed": 7, "value": 1}
    assert replayed.current_step == 1
