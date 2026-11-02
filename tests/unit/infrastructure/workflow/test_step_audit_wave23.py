"""ADR-0414 — аудит шагов workflow (pg-runner): unit-тесты.

Проверяется модель «шаг workflow для аудита»:

* аудит-эмит на старте шага (``started``) и на терминальном исходе
  (``succeeded`` / ``failed`` / ``cancelled``);
* метаданные (route_id / step / tenant / attempt / outcome /
  duration_ms / capability) — и **никаких** значений данных шага;
* идемпотентность: повторный запуск шага не дублирует событие старта;
* гейт: без декларации capability ``audit.write`` событий нет.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest

from src.backend.core.domain.models.workflow_event import WorkflowEventType
from src.backend.core.domain.models.workflow_instance import WorkflowStatus
from src.backend.core.security.capabilities.gate import get_capability_gate
from src.backend.core.security.capabilities.models import CapabilityRef
from src.backend.infrastructure.workflow.executor.state import StepDescriptor
from src.backend.infrastructure.workflow.pg_runner_internals import (
    WorkflowEventRow,
    WorkflowInstanceRow,
)
from src.backend.infrastructure.workflow.pg_runner_internals.step_audit import (
    AUDIT_CAPABILITY,
    PHASE_CANCELLED,
    PHASE_FAILED,
    PHASE_STARTED,
    PHASE_SUCCEEDED,
    emit_step_audit,
    step_audit_enabled,
)
from src.backend.infrastructure.workflow.runner import (
    DurableWorkflowRunner,
    RunnerConfig,
    StepOutcome,
    StepResult,
)

pytestmark = pytest.mark.unit

ROUTE_ID = "route.audit.demo"
TENANT_ID = "tenant-a"
STEP_NAME = "charge_card"


# ─────────────────────────── фикстуры ───────────────────────────


@pytest.fixture
def audit_calls(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Перехват audit-событий unified audit-сервиса."""
    calls: list[dict[str, Any]] = []

    def _fake_emit_audit(event: str, **kwargs: Any) -> None:
        calls.append({"event": event, **kwargs})

    monkeypatch.setattr(
        "src.backend.core.audit.facade.emit_audit", _fake_emit_audit, raising=True
    )
    return calls


@pytest.fixture
def audit_capability() -> Iterator[None]:
    """Роут объявляет capability ``audit.write`` — аудит шагов включён.

    Декларация снимается в teardown'е через ``revoke`` (а не через
    ``cache_clear``) — процессный гейт общий, чужие декларации роутов
    терять нельзя (ADR-0410 — order-dependent загрязнение).
    """
    gate = get_capability_gate()
    gate.revoke(ROUTE_ID)
    gate.declare(ROUTE_ID, [CapabilityRef(name=AUDIT_CAPABILITY, scope="*")])
    yield
    gate.revoke(ROUTE_ID)


def _instance(status: WorkflowStatus = WorkflowStatus.running) -> WorkflowInstanceRow:
    now = datetime.now(UTC)
    return WorkflowInstanceRow(
        id=uuid.uuid4(),
        workflow_name="demo.flow",
        route_id=ROUTE_ID,
        status=status,
        current_version=1,
        last_event_seq=None,
        snapshot_state=None,
        next_attempt_at=None,
        locked_by="worker",
        locked_until=now,
        tenant_id=TENANT_ID,
        input_payload={},
        created_at=now,
        updated_at=now,
        finished_at=None,
    )


class _FakeEventStore:
    """Event log в памяти (append-only, как настоящий store)."""

    def __init__(self, workflow_id: uuid.UUID) -> None:
        self.events: list[WorkflowEventRow] = []
        self._seq = 0
        self._workflow_id = workflow_id
        self._seed_created()

    def _seed_created(self) -> None:
        self._append(
            WorkflowEventType.created,
            {"workflow_name": "demo.flow", "route_id": ROUTE_ID},
            None,
        )

    def _append(
        self,
        event_type: WorkflowEventType,
        payload: dict[str, Any],
        step_name: str | None,
    ) -> int:
        self._seq += 1
        self.events.append(
            WorkflowEventRow(
                seq=self._seq,
                workflow_id=self._workflow_id,
                event_type=event_type,
                payload=dict(payload),
                step_name=step_name,
                occurred_at=datetime.now(UTC),
            )
        )
        return self._seq

    async def append(
        self,
        workflow_id: uuid.UUID,
        event_type: WorkflowEventType,
        payload: dict[str, Any],
        step_name: str | None = None,
    ) -> int:
        return self._append(event_type, payload, step_name)

    async def read_events(
        self, workflow_id: uuid.UUID, after_seq: int = 0, limit: int = 1000
    ) -> list[WorkflowEventRow]:
        return [e for e in self.events if e.seq > after_seq][:limit]

    async def snapshot(
        self, workflow_id: uuid.UUID, state: dict[str, Any], at_seq: int
    ) -> None:
        self._append(WorkflowEventType.snapshotted, {"at_seq": at_seq}, None)


class _FakeStateStore:
    """Header-хранилище инстанса в памяти."""

    def __init__(self, instance: WorkflowInstanceRow) -> None:
        self.instance = instance

    async def try_lock(
        self, workflow_id: uuid.UUID, worker_id: str, ttl_s: int
    ) -> bool:
        return True

    async def renew_lock(
        self, workflow_id: uuid.UUID, worker_id: str, ttl_s: int
    ) -> bool:
        return True

    async def unlock(self, workflow_id: uuid.UUID, worker_id: str) -> None:
        return None

    async def get(self, workflow_id: uuid.UUID) -> WorkflowInstanceRow | None:
        return self.instance

    async def update_status(
        self,
        workflow_id: uuid.UUID,
        status: WorkflowStatus,
        next_attempt_at: datetime | None = None,
        error: str | None = None,
    ) -> None:
        self.instance = replace(self.instance, status=status)


class _FakeExecutor:
    """Executor с pre-step протоколом (``describe_next``)."""

    def __init__(self, result: StepResult, *, step_name: str = STEP_NAME) -> None:
        self._result = result
        self._step_name = step_name
        self.calls = 0

    def describe_next(
        self, instance: WorkflowInstanceRow, state: Any
    ) -> StepDescriptor | None:
        return StepDescriptor(name=self._step_name, kind="sequential", attempt=1)

    async def execute_next(
        self, *, instance: WorkflowInstanceRow, state: Any
    ) -> StepResult:
        self.calls += 1
        return self._result


def _build_runner(
    instance: WorkflowInstanceRow, result: StepResult
) -> tuple[DurableWorkflowRunner, _FakeEventStore]:
    """Runner с фейковыми store'ами и executor'ом."""
    event_store = _FakeEventStore(instance.id)
    state_store = _FakeStateStore(instance)
    runner = DurableWorkflowRunner(
        config=RunnerConfig(worker_id="test-worker"),
        executor=_FakeExecutor(result),
        state_store=state_store,  # type: ignore[arg-type]
        event_store=event_store,  # type: ignore[arg-type]
    )
    # Heartbeat не нужен в unit-тесте — фоновой lease-task мешает.
    runner._start_heartbeat = lambda workflow_id: None  # type: ignore[method-assign]
    return runner, event_store


def _success_result() -> StepResult:
    return StepResult(
        outcome=StepOutcome.CONTINUE,
        events=[
            (
                WorkflowEventType.step_finished,
                {"next_step": 1, "exchange": {"iban": "DE000", "pin": "s3cr3t"}},
                STEP_NAME,
            )
        ],
        output_state={"exchange_snapshot": {"iban": "DE000", "pin": "s3cr3t"}},
    )


def _failed_result() -> StepResult:
    return StepResult(
        outcome=StepOutcome.PAUSE,
        error_message="boom",
        events=[
            (
                WorkflowEventType.step_failed,
                {"error": "boom", "attempt": 1, "payload": {"pin": "s3cr3t"}},
                STEP_NAME,
            )
        ],
        attempts=1,
        max_attempts=10,
    )


def _events_by_name(calls: list[dict[str, Any]], event: str) -> list[dict[str, Any]]:
    return [call for call in calls if call["event"] == event]


# ─────────────────────────── тесты ───────────────────────────


@pytest.mark.asyncio
async def test_started_and_succeeded_emitted_with_metadata(
    audit_calls: list[dict[str, Any]], audit_capability: None
) -> None:
    """Шаг: события started + succeeded с полными метаданными."""
    instance = _instance()
    runner, _events = _build_runner(instance, _success_result())

    await runner._run_step(instance.id)

    started = _events_by_name(audit_calls, "workflow.step.started")
    succeeded = _events_by_name(audit_calls, "workflow.step.succeeded")
    assert len(started) == 1
    assert len(succeeded) == 1

    details = started[0]["details"]
    assert details["route_id"] == ROUTE_ID
    assert details["step"] == STEP_NAME
    assert details["tenant"] == TENANT_ID
    assert details["attempt"] == 1
    assert details["outcome"] == PHASE_STARTED
    assert details["capability"] == AUDIT_CAPABILITY
    assert details["workflow_id"] == str(instance.id)
    assert details["duration_ms"] == 0.0
    assert started[0]["actor"] == f"workflow_step:{STEP_NAME}"
    assert started[0]["resource"] == f"workflow_step:{STEP_NAME}"
    assert started[0]["action"] == "execute"
    assert started[0]["outcome"] == PHASE_STARTED

    terminal_details = succeeded[0]["details"]
    assert terminal_details["outcome"] == PHASE_SUCCEEDED
    assert terminal_details["attempt"] == 1
    assert terminal_details["route_id"] == ROUTE_ID
    assert terminal_details["step"] == STEP_NAME
    assert terminal_details["duration_ms"] >= 0.0


@pytest.mark.asyncio
async def test_failed_step_emits_failed_event(
    audit_calls: list[dict[str, Any]], audit_capability: None
) -> None:
    """Упавший шаг → событие workflow.step.failed с outcome=failed."""
    instance = _instance()
    runner, _events = _build_runner(instance, _failed_result())

    await runner._run_step(instance.id)

    failed = _events_by_name(audit_calls, "workflow.step.failed")
    assert len(failed) == 1
    assert failed[0]["outcome"] == PHASE_FAILED
    assert failed[0]["details"]["outcome"] == PHASE_FAILED
    assert failed[0]["details"]["step"] == STEP_NAME
    assert failed[0]["details"]["attempt"] == 1
    assert not _events_by_name(audit_calls, "workflow.step.succeeded")


@pytest.mark.asyncio
async def test_cancelled_workflow_emits_cancelled_event(
    audit_calls: list[dict[str, Any]], audit_capability: None
) -> None:
    """Отмена workflow'а → событие workflow.step.cancelled для pending-шага."""
    instance = _instance(status=WorkflowStatus.cancelling)
    runner, _events = _build_runner(instance, _success_result())

    await runner._run_step(instance.id)

    cancelled = _events_by_name(audit_calls, "workflow.step.cancelled")
    assert len(cancelled) == 1
    assert cancelled[0]["outcome"] == PHASE_CANCELLED
    assert cancelled[0]["details"]["step"] == STEP_NAME
    assert cancelled[0]["details"]["route_id"] == ROUTE_ID
    # Шаг не исполнялся — события старта/успеха нет.
    assert not _events_by_name(audit_calls, "workflow.step.started")
    assert not _events_by_name(audit_calls, "workflow.step.succeeded")


@pytest.mark.asyncio
async def test_step_payload_not_leaked_into_audit_event(
    audit_calls: list[dict[str, Any]], audit_capability: None
) -> None:
    """Payload шага (данные) в audit-событие не попадает."""
    instance = _instance()
    runner, _events = _build_runner(instance, _success_result())

    await runner._run_step(instance.id)

    assert audit_calls
    blob = json.dumps(audit_calls, default=str, ensure_ascii=False)
    assert "DE000" not in blob
    assert "s3cr3t" not in blob
    assert "iban" not in blob
    assert "pin" not in blob


@pytest.mark.asyncio
async def test_rerun_does_not_duplicate_started_event(
    audit_calls: list[dict[str, Any]], audit_capability: None
) -> None:
    """Повторный запуск шага не дублирует событие старта."""
    instance = _instance()
    runner, _events = _build_runner(instance, _success_result())

    await runner._run_step(instance.id)
    await runner._run_step(instance.id)

    started = _events_by_name(audit_calls, "workflow.step.started")
    assert len(started) == 1
    succeeded = _events_by_name(audit_calls, "workflow.step.succeeded")
    assert len(succeeded) == 1


@pytest.mark.asyncio
async def test_no_audit_without_audit_write_capability(
    audit_calls: list[dict[str, Any]],
) -> None:
    """Без декларации capability audit.write событий нет."""
    gate = get_capability_gate()
    gate.revoke(ROUTE_ID)
    instance = _instance()
    runner, _events = _build_runner(instance, _success_result())

    await runner._run_step(instance.id)

    assert audit_calls == []
    gate.revoke(ROUTE_ID)


def test_step_audit_enabled_reflects_declaration() -> None:
    """``step_audit_enabled`` — по декларации capability роутом."""
    gate = get_capability_gate()
    gate.revoke(ROUTE_ID)
    assert step_audit_enabled(ROUTE_ID) is False
    gate.declare(ROUTE_ID, [CapabilityRef(name=AUDIT_CAPABILITY, scope="*")])
    assert step_audit_enabled(ROUTE_ID) is True
    assert step_audit_enabled("") is False
    gate.revoke(ROUTE_ID)


def test_emit_step_audit_rejects_unknown_phase(
    audit_calls: list[dict[str, Any]], audit_capability: None
) -> None:
    """Неизвестная фаза → событие не эмитится."""
    assert (
        emit_step_audit(
            phase="teleported",
            route_id=ROUTE_ID,
            step=STEP_NAME,
            tenant_id=TENANT_ID,
            attempt=1,
        )
        is False
    )
    assert audit_calls == []
