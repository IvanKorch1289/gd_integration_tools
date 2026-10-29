"""Wave 19 / ADR-0396 — компенсации Saga в pg-runner-пути (кластер C).

Закрывает дефекты ревью:

* (1) [high] компенсации в pg-runner НЕ исполнялись (``kind="compensate"``
  → no-op, runner при FAILED только пишет статус);
* (2) [medium] docstring ``compensate``-шага обещал откат runner'ом;
* (3) [medium] бюджет времени workflow нигде не применялся.

Тесты покрывают: reverse-порядок компенсаций, цепочку исключений при
ошибке компенсации, явный ``compensate_map`` и time-budget.
"""

from __future__ import annotations

import asyncio
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.core.domain.models.workflow_event import WorkflowEventType
from src.backend.core.domain.models.workflow_instance import WorkflowStatus
from src.backend.infrastructure.workflow.compensating_driver import (
    CompensatingDriverWorker,
)
from src.backend.infrastructure.workflow.executor import DSLStepExecutor
from src.backend.infrastructure.workflow.executor.compensating import (
    CompensationError,
    build_compensation_plan,
    execute_compensation,
)
from src.backend.infrastructure.workflow.executor.state import (
    WorkflowSpec,
    WorkflowStep,
)
from src.backend.infrastructure.workflow.pg_runner_internals import (
    WorkflowInstanceRow,
    WorkflowState,
)
from src.backend.infrastructure.workflow.runner import StepOutcome

# ── helpers ─────────────────────────────────────────────────────────


def _proc(
    name: str,
    calls: list[str],
    *,
    delay: float = 0.0,
    fail_with: Exception | None = None,
) -> Any:
    """Создать processor-корутину, фиксирующую вызов в ``calls``."""

    async def _run(exchange: Any) -> Any:
        calls.append(name)
        if delay:
            await asyncio.sleep(delay)
        if fail_with is not None:
            raise fail_with
        return exchange

    _run.__name__ = name
    return _run


def _instance(
    *,
    created_at: datetime | None = None,
    input_payload: dict[str, Any] | None = None,
) -> WorkflowInstanceRow:
    """WorkflowInstanceRow для юнит-тестов executor'а."""
    now = datetime.now(UTC)
    return WorkflowInstanceRow(
        id=uuid.uuid4(),
        workflow_name="wf-test",
        route_id="route-test",
        status=WorkflowStatus.running,
        current_version=1,
        last_event_seq=None,
        snapshot_state=None,
        next_attempt_at=None,
        locked_by="worker",
        locked_until=now,
        tenant_id="default",
        input_payload=input_payload or {},
        created_at=created_at or now,
        updated_at=now,
        finished_at=None,
    )


def _state(*, current_step: int = 0, history: list[str] | None = None) -> WorkflowState:
    """Materialized state с заданным cursor'ом и историей шагов."""
    return WorkflowState(
        workflow_id=uuid.uuid4(),
        current_step=current_step,
        step_history=list(history or []),
    )


def _executor(spec: WorkflowSpec, *, timeout_per_step_s: float = 5.0) -> DSLStepExecutor:
    """DSLStepExecutor с фиксированным spec'ом."""
    return DSLStepExecutor(
        spec_loader=lambda _route_id: spec,
        timeout_per_step_s=timeout_per_step_s,
    )


def _saga_spec(calls: list[str]) -> WorkflowSpec:
    """Spec саги: два forward-шага + два rollback-шага (позиционный маппинг)."""
    return WorkflowSpec(
        name="wf-saga",
        steps=(
            WorkflowStep(
                kind="sequential", name="reserve", processors=(_proc("reserve", calls),)
            ),
            WorkflowStep(
                kind="sequential", name="charge", processors=(_proc("charge", calls),)
            ),
            WorkflowStep(
                kind="compensate",
                name="undo_reserve",
                processors=(_proc("undo_reserve", calls),),
            ),
            WorkflowStep(
                kind="compensate",
                name="undo_charge",
                processors=(_proc("undo_charge", calls),),
            ),
        ),
    )


# ── (1) план компенсаций: reverse-порядок ──────────────────────────


def test_compensation_plan_is_reverse_order() -> None:
    """Компенсации строятся в обратном порядке относительно forward-шагов."""
    spec = _saga_spec([])

    plan = build_compensation_plan(spec, completed_names=["reserve", "charge"])

    assert [action.step.name for action in plan] == ["undo_charge", "undo_reserve"]
    assert [action.forward_name for action in plan] == ["charge", "reserve"]


def test_compensation_plan_skips_uncompleted_steps() -> None:
    """Незавершённые forward-шаги не компенсируются."""
    spec = _saga_spec([])

    plan = build_compensation_plan(spec, completed_names=["reserve"])

    assert [action.step.name for action in plan] == ["undo_reserve"]


def test_compensation_plan_uses_explicit_compensate_map() -> None:
    """Явный compensate_map важнее позиционного маппинга."""
    spec = WorkflowSpec(
        name="wf-saga",
        steps=(
            WorkflowStep(kind="sequential", name="reserve", processors=()),
            WorkflowStep(kind="sequential", name="charge", processors=()),
            WorkflowStep(kind="compensate", name="undo_reserve", processors=()),
            WorkflowStep(kind="compensate", name="undo_charge", processors=()),
        ),
        compensate_map={"reserve": "undo_charge", "charge": "undo_reserve"},
    )

    plan = build_compensation_plan(spec, completed_names=["reserve", "charge"])

    assert [action.step.name for action in plan] == ["undo_reserve", "undo_charge"]


# ── (1) цепочка исключений при ошибке компенсации ───────────────────


@pytest.mark.asyncio
async def test_execute_compensation_chains_exceptions() -> None:
    """Ошибка компенсации → chain: original + ошибки компенсаций."""
    spec = _saga_spec([])
    plan = build_compensation_plan(spec, completed_names=["reserve"])
    original = RuntimeError("forward step failed")
    comp_error = ValueError("rollback refused")

    async def _execute(step: WorkflowStep) -> None:
        raise comp_error

    with pytest.raises(CompensationError) as exc_info:
        await execute_compensation(
            plan=plan,
            execute=_execute,
            original_error=original,
            strict=True,
        )

    err = exc_info.value
    assert err.original is original
    assert err.errors == (comp_error,)
    assert err.__cause__ is comp_error


@pytest.mark.asyncio
async def test_execute_compensation_non_strict_returns_outcome() -> None:
    """strict=False — ошибки не поднимаются, а возвращаются в outcome."""
    spec = _saga_spec([])
    plan = build_compensation_plan(spec, completed_names=["reserve"])
    comp_error = ValueError("rollback refused")

    async def _execute(step: WorkflowStep) -> None:
        raise comp_error

    outcome = await execute_compensation(
        plan=plan,
        execute=_execute,
        original_error=RuntimeError("forward step failed"),
        strict=False,
    )

    assert outcome.failed is True
    assert outcome.errors == (comp_error,)
    assert outcome.executed == ()


# ── (1) executor: компенсация исполняется при терминальном FAILED ───


@pytest.mark.asyncio
async def test_executor_runs_compensation_on_failed_step() -> None:
    """FAILED-шаг → компенсация выполненных forward-шагов (pg-runner)."""
    calls: list[str] = []
    spec = WorkflowSpec(
        name="wf-saga",
        steps=(
            WorkflowStep(
                kind="sequential", name="reserve", processors=(_proc("reserve", calls),)
            ),
            WorkflowStep(
                kind="sequential",
                name="charge",
                processors=(_proc("charge", calls, delay=0.5),),
            ),
            WorkflowStep(
                kind="compensate",
                name="undo_reserve",
                processors=(_proc("undo_reserve", calls),),
            ),
        ),
    )
    executor = _executor(spec, timeout_per_step_s=0.05)
    state = _state(current_step=1, history=["reserve"])

    result = await executor.execute_next(
        instance=_instance(), state=state
    )

    assert result.outcome == StepOutcome.FAILED
    assert "undo_reserve" in calls
    assert any(
        event_type is WorkflowEventType.compensated
        for event_type, _payload, _name in result.events
    )


@pytest.mark.asyncio
async def test_executor_compensation_runs_in_reverse_order() -> None:
    """Компенсации двух forward-шагов исполняются в обратном порядке."""
    calls: list[str] = []
    spec = _saga_spec(calls)
    spec.steps[1].processors = (_proc("charge", calls, delay=0.5),)
    executor = _executor(spec, timeout_per_step_s=0.05)
    state = _state(current_step=1, history=["reserve", "charge"])

    result = await executor.execute_next(instance=_instance(), state=state)

    assert result.outcome == StepOutcome.FAILED
    compensation_calls = [c for c in calls if c.startswith("undo_")]
    assert compensation_calls == ["undo_charge", "undo_reserve"]


@pytest.mark.asyncio
async def test_executor_compensation_failure_is_reported() -> None:
    """Ошибка компенсации попадает в error_message и в событие compensated."""
    calls: list[str] = []
    spec = WorkflowSpec(
        name="wf-saga",
        steps=(
            WorkflowStep(
                kind="sequential", name="reserve", processors=(_proc("reserve", calls),)
            ),
            WorkflowStep(
                kind="sequential",
                name="charge",
                processors=(_proc("charge", calls, delay=0.5),),
            ),
            WorkflowStep(
                kind="compensate",
                name="undo_reserve",
                processors=(_proc("undo_reserve", calls, fail_with=ValueError("nope")),),
            ),
        ),
    )
    executor = _executor(spec, timeout_per_step_s=0.05)
    state = _state(current_step=1, history=["reserve"])

    result = await executor.execute_next(instance=_instance(), state=state)

    assert result.outcome == StepOutcome.FAILED
    assert result.error_message is not None
    assert "compensation failed" in result.error_message
    compensated = [
        payload
        for event_type, payload, _name in result.events
        if event_type is WorkflowEventType.compensated
    ]
    assert compensated and compensated[0]["status"] == "failed"


@pytest.mark.asyncio
async def test_executor_without_compensation_keeps_failed_result() -> None:
    """Spec без compensate-шагов → FAILED без compensated-событий."""
    calls: list[str] = []
    spec = WorkflowSpec(
        name="wf-plain",
        steps=(
            WorkflowStep(
                kind="sequential",
                name="charge",
                processors=(_proc("charge", calls, delay=0.5),),
            ),
        ),
    )
    executor = _executor(spec, timeout_per_step_s=0.05)

    result = await executor.execute_next(
        instance=_instance(), state=_state(current_step=0)
    )

    assert result.outcome == StepOutcome.FAILED
    assert not any(
        event_type is WorkflowEventType.compensated
        for event_type, _payload, _name in result.events
    )


# ── (3) бюджет времени workflow ─────────────────────────────────────


@pytest.mark.asyncio
async def test_execution_timeout_from_payload_fails_workflow() -> None:
    """Исчерпанный execution_timeout → FAILED, шаг не исполняется."""
    calls: list[str] = []
    spec = WorkflowSpec(
        name="wf-plain",
        steps=(
            WorkflowStep(
                kind="sequential", name="charge", processors=(_proc("charge", calls),)
            ),
        ),
    )
    executor = _executor(spec)
    instance = _instance(
        created_at=datetime.now(UTC) - timedelta(seconds=120),
        input_payload={"__execution_timeout_s": 30.0},
    )

    result = await executor.execute_next(instance=instance, state=_state())

    assert result.outcome == StepOutcome.FAILED
    assert result.error_message is not None
    assert "execution timeout" in result.error_message
    assert calls == []


@pytest.mark.asyncio
async def test_spec_run_timeout_is_enforced() -> None:
    """Spec-level run_timeout_s — тоже бюджет времени."""
    calls: list[str] = []
    spec = WorkflowSpec(
        name="wf-plain",
        steps=(
            WorkflowStep(
                kind="sequential", name="charge", processors=(_proc("charge", calls),)
            ),
        ),
        run_timeout_s=10.0,
    )
    executor = _executor(spec)
    instance = _instance(created_at=datetime.now(UTC) - timedelta(seconds=60))

    result = await executor.execute_next(instance=instance, state=_state())

    assert result.outcome == StepOutcome.FAILED
    assert calls == []


@pytest.mark.asyncio
async def test_within_budget_step_is_executed() -> None:
    """В пределах бюджета шаг исполняется как обычно."""
    calls: list[str] = []
    spec = WorkflowSpec(
        name="wf-plain",
        steps=(
            WorkflowStep(
                kind="sequential", name="charge", processors=(_proc("charge", calls),)
            ),
        ),
        run_timeout_s=600.0,
    )
    executor = _executor(spec)

    result = await executor.execute_next(
        instance=_instance(), state=_state(current_step=0)
    )

    assert result.outcome == StepOutcome.CONTINUE
    assert calls == ["charge"]


@pytest.mark.asyncio
async def test_finished_workflow_is_not_failed_by_budget() -> None:
    """Исчерпанный бюджет не превращает уже завершённый workflow в FAILED."""
    spec = WorkflowSpec(
        name="wf-plain",
        steps=(
            WorkflowStep(kind="sequential", name="charge", processors=()),
        ),
        run_timeout_s=1.0,
    )
    executor = _executor(spec)
    instance = _instance(created_at=datetime.now(UTC) - timedelta(seconds=600))

    result = await executor.execute_next(
        instance=instance, state=_state(current_step=1)
    )

    assert result.outcome == StepOutcome.DONE


# ── (1) CompensatingDriverWorker не теряет компенсации ──────────────


class _FakeSagaRepo:
    """Fake WorkflowStateRepository для driver'а."""

    def __init__(self, sagas: list[MagicMock]) -> None:
        self._sagas = sagas
        self.signal_calls: list[str] = []

    async def list_compensating(self, *, tenant_id: Any = None, limit: int = 100) -> list:
        """Вернуть застрявшие саги."""
        return list(self._sagas)

    async def signal_event(self, workflow_id: Any, run_id: Any, *, event: str) -> Any:
        """Зафиксировать переход состояния."""
        self.signal_calls.append(event)
        return MagicMock(state=event)


@asynccontextmanager
async def _fake_session() -> Any:
    """Fake async session (без БД)."""
    yield MagicMock()


def _fake_session_factory() -> Any:
    """Фабрика fake-сессии для driver'а."""
    return _fake_session()


def _session_factory() -> MagicMock:
    """MagicMock session_factory, открывающий fake-сессию."""
    factory = MagicMock()
    factory.__class__.__module__ = "fake"
    factory.return_value.__aenter__ = AsyncMock(side_effect=_fake_session_factory)
    factory.return_value.__aexit__ = AsyncMock(return_value=False)
    return factory


@pytest.mark.asyncio
async def test_driver_keeps_saga_with_pending_compensations() -> None:
    """Saga с неисполненными компенсациями НЕ помечается rolled_back."""
    saga = MagicMock()
    saga.workflow_id = uuid.uuid4()
    saga.run_id = "run-1"
    saga.tenant_id = "default"
    saga.compensating_actions = [{"step_index": 0, "compensate_name": "undo"}]
    fake_repo = _FakeSagaRepo([saga])

    with patch(
        "src.backend.infrastructure.workflow.saga_state.WorkflowStateRepository"
    ) as mock_repo:
        mock_repo.return_value = fake_repo
        worker = CompensatingDriverWorker(session_factory=_session_factory())
        await worker._scan_once()

    assert fake_repo.signal_calls == []

