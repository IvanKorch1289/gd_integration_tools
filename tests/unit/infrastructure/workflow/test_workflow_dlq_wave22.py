"""ADR-0408 (волна 22): DLQ-контракт для исчерпавших попыток шагов workflow.

Дефект (до фикса)
-----------------
Исчерпание retry-бюджета шага давало терминальный ``FAILED`` + метрику
``record_workflow_status``, но **не** оставляло записи в DLQ: исчерпанный
шаг терялся, разбирать его было негде (ADR-0403 §Открытое, «Workflow-DLQ»).

Ожидание
--------
* исчерпанный шаг попадает в messaging-DLQ (``DLQEnvelope``, transport
  ``workflow``) с route_id / step / attempts / причиной / tenant и
  payload-метаданными **без значений данных**;
* шаг при этом переходит в терминальный ``FAILED``;
* повторный запуск не дублирует запись (идемпотентность по ``dlq_id``).
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from prometheus_client import REGISTRY

from src.backend.core.domain.models.workflow_event import WorkflowEventType
from src.backend.core.domain.models.workflow_instance import WorkflowStatus
from src.backend.infrastructure.messaging.dlq.memory_writer import InMemoryDLQWriter
from src.backend.infrastructure.workflow.pg_runner_backend import (
    PgRunnerWorkflowBackend,
)
from src.backend.infrastructure.workflow.pg_runner_internals.workflow_dlq import (
    WORKFLOW_DLQ_TRANSPORT,
    WorkflowDLQPublisher,
    build_exhausted_step_envelope,
)
from src.backend.infrastructure.workflow.runner import (
    DurableWorkflowRunner,
    RunnerConfig,
    StepOutcome,
    StepResult,
)

pytestmark = pytest.mark.unit


def _make_instance(**overrides: object) -> object:
    """Row workflow-инстанса для DLQ-контракта."""
    now = datetime.now(UTC)
    kwargs: dict[str, object] = {
        "id": uuid.uuid4(),
        "workflow_name": "orders.saga",
        "route_id": "orders_saga",
        "status": WorkflowStatus.running,
        "current_version": 1,
        "last_event_seq": None,
        "snapshot_state": None,
        "next_attempt_at": None,
        "locked_by": "worker-1",
        "locked_until": now,
        "tenant_id": "tenant-42",
        "input_payload": {"order_id": "A-1", "amount": 100},
        "created_at": now,
        "updated_at": now,
        "finished_at": None,
    }
    kwargs.update(overrides)
    return type("Instance", (), kwargs)()


def _build_runner(dlq_writer: object | None = None) -> DurableWorkflowRunner:
    """Runner с мок-сторами (без БД)."""
    state_store = MagicMock(name="state_store")
    state_store.update_status = AsyncMock(name="update_status")
    event_store = MagicMock(name="event_store")
    event_store.append = AsyncMock(name="append", return_value=1)
    executor = MagicMock(name="executor")
    return DurableWorkflowRunner(
        config=RunnerConfig(worker_id="test-worker"),
        executor=executor,
        state_store=state_store,
        event_store=event_store,
        dlq_writer=dlq_writer,
    )


# ── Контракт envelope'а ────────────────────────────────────────────────


def test_envelope_contains_step_metadata_without_payload_values() -> None:
    """Envelope несёт route_id/step/attempts/tenant, но не значения данных."""
    instance = _make_instance()
    envelope = build_exhausted_step_envelope(
        dlq_id="dlq-1",
        instance=instance,
        step_name="charge_card",
        attempts=3,
        max_attempts=3,
        error_message="TimeoutError: gateway timeout",
        payload_keys=["order_id", "amount"],
    )

    assert envelope.transport == WORKFLOW_DLQ_TRANSPORT
    assert envelope.route_id == "orders_saga"
    assert envelope.tenant_id == "tenant-42"
    assert envelope.retry_count == 3
    assert envelope.reason == "retries_exhausted"
    assert envelope.metadata["step"] == "charge_card"
    assert envelope.metadata["attempts"] == 3
    assert envelope.metadata["max_attempts"] == 3
    assert envelope.metadata["workflow_id"] == str(instance.id)
    # payload-метаданные — только имена ключей, без значений.
    assert envelope.metadata["payload_keys"] == ["order_id", "amount"]
    assert envelope.original_payload is None
    dumped = envelope.model_dump_json()
    assert "A-1" not in dumped, "значения данных workflow не должны попадать в DLQ"


# ── Runner: исчерпание попыток → DLQ + терминальный FAILED ────────────


@pytest.mark.asyncio
async def test_exhausted_step_goes_to_dlq_and_fails_terminally() -> None:
    """Исчерпанный шаг → запись в DLQ + терминальный FAILED."""
    writer = InMemoryDLQWriter()
    runner = _build_runner(dlq_writer=writer)
    instance = _make_instance()
    result = StepResult(
        outcome=StepOutcome.FAILED,
        error_message="TimeoutError: gateway timeout",
        attempts=3,
        max_attempts=3,
    )

    await runner._apply_outcome(instance.id, result, MagicMock(), instance)

    assert len(writer.records) == 1
    envelope = writer.records[0]
    assert envelope.transport == WORKFLOW_DLQ_TRANSPORT
    assert envelope.route_id == "orders_saga"
    assert envelope.tenant_id == "tenant-42"
    assert envelope.retry_count == 3
    assert envelope.metadata["step"] == "unknown"

    runner._state_store.update_status.assert_awaited_once_with(
        instance.id, WorkflowStatus.failed, error="TimeoutError: gateway timeout"
    )


@pytest.mark.asyncio
async def test_pause_with_exhausted_budget_goes_to_dlq() -> None:
    """PAUSE с исчерпанным бюджетом → DLQ + терминальный FAILED."""
    writer = InMemoryDLQWriter()
    runner = _build_runner(dlq_writer=writer)
    instance = _make_instance()
    result = StepResult(
        outcome=StepOutcome.PAUSE,
        error_message="step failed",
        attempts=5,
        max_attempts=5,
    )

    await runner._apply_outcome(instance.id, result, MagicMock(), instance)

    assert len(writer.records) == 1
    assert writer.records[0].retry_count == 5
    assert runner._state_store.update_status.await_args.args[1] is (
        WorkflowStatus.failed
    )


@pytest.mark.asyncio
async def test_repeated_exhaustion_does_not_duplicate_dlq_record() -> None:
    """Повторный запуск того же шага не дублирует запись в DLQ."""
    writer = InMemoryDLQWriter()
    runner = _build_runner(dlq_writer=writer)
    instance = _make_instance()
    result = StepResult(
        outcome=StepOutcome.FAILED, error_message="boom", attempts=2, max_attempts=2
    )

    await runner._apply_outcome(instance.id, result, MagicMock(), instance)
    await runner._apply_outcome(instance.id, result, MagicMock(), instance)

    assert len(writer.records) == 1, "повторный запуск не должен дублировать запись"


@pytest.mark.asyncio
async def test_non_exhausted_failure_does_not_go_to_dlq() -> None:
    """Терминальный FAILED без исчерпания бюджета в DLQ не попадает."""
    writer = InMemoryDLQWriter()
    runner = _build_runner(dlq_writer=writer)
    instance = _make_instance()
    result = StepResult(
        outcome=StepOutcome.FAILED,
        error_message="spec not found",
        attempts=1,
        max_attempts=3,
    )

    await runner._apply_outcome(instance.id, result, MagicMock(), instance)

    assert writer.records == []


@pytest.mark.asyncio
async def test_missing_dlq_writer_does_not_break_workflow() -> None:
    """DLQ недоступен (writer'а нет / запись падает) — workflow не падает."""
    runner = _build_runner(dlq_writer=None)
    instance = _make_instance()
    result = StepResult(
        outcome=StepOutcome.FAILED, error_message="boom", attempts=3, max_attempts=3
    )

    await runner._apply_outcome(instance.id, result, MagicMock(), instance)

    runner._state_store.update_status.assert_awaited_once()


@pytest.mark.asyncio
async def test_publisher_without_writer_reports_no_writer_status() -> None:
    """Без writer'а публикация пропускается и фиксируется статус no_writer."""
    publisher = WorkflowDLQPublisher(None)
    instance = _make_instance()

    published = await publisher.publish_exhausted_step(
        dlq_id="dlq-no-writer",
        instance=instance,
        step_name="charge_card",
        attempts=3,
        max_attempts=3,
        error_message="boom",
    )

    assert published is False
    assert (
        REGISTRY.get_sample_value("workflow_dlq_publish_total", {"status": "no_writer"})
        == 1
    )


@pytest.mark.asyncio
async def test_publisher_is_idempotent_for_writers_without_dedup() -> None:
    """Даже writer без дедупликации получает одну запись на шаг+попытку."""

    class _NaiveWriter:
        def __init__(self) -> None:
            self.records: list[object] = []

        async def write(self, envelope: object) -> None:
            self.records.append(envelope)

    naive = _NaiveWriter()
    publisher = WorkflowDLQPublisher(naive)
    instance = _make_instance()

    for _ in range(3):
        await publisher.publish_exhausted_step(
            dlq_id="dlq-fixed",
            instance=instance,
            step_name="charge_card",
            attempts=3,
            max_attempts=3,
            error_message="boom",
        )

    assert len(naive.records) == 1


# ── DLQ-replay: переигровка исчерпанного шага (pg_runner_backend) ────


def _build_backend(instance: object) -> PgRunnerWorkflowBackend:
    """Backend с мок-сторами (без БД)."""
    state_store = MagicMock(name="state_store")
    state_store.get = AsyncMock(name="get", return_value=instance)
    state_store.update_status = AsyncMock(name="update_status")
    event_store = MagicMock(name="event_store")
    event_store.append = AsyncMock(name="append", return_value=7)
    backend = PgRunnerWorkflowBackend(state_store=state_store, event_store=event_store)
    backend._state_store = state_store
    backend._event_store = event_store
    return backend


@pytest.mark.asyncio
async def test_replay_resets_retry_budget_and_requeues_instance() -> None:
    """DLQ-replay: сброс retry-бюджета + возврат инстанса в pending."""
    instance = _make_instance(status=WorkflowStatus.failed)
    backend = _build_backend(instance)
    history = json.dumps(
        {"workflow_id": str(instance.id), "step": "charge_card", "attempts": 3}
    ).encode()

    await backend.replay(workflow_name="orders.saga", history=history)

    state_store = backend._state_store
    event_store = backend._event_store
    append_kwargs = event_store.append.await_args.kwargs
    assert append_kwargs["event_type"] == WorkflowEventType.resumed
    assert append_kwargs["payload"]["attempts_reset"] is True
    assert append_kwargs["payload"]["step"] == "charge_card"
    update_kwargs = state_store.update_status.await_args.kwargs
    assert update_kwargs["status"] is WorkflowStatus.pending
    assert update_kwargs["next_attempt_at"] is not None


@pytest.mark.asyncio
async def test_replay_accepts_full_dlq_envelope_payload() -> None:
    """Принимается и полная DLQ-запись (metadata внутри)."""
    instance = _make_instance(status=WorkflowStatus.failed)
    backend = _build_backend(instance)
    history = json.dumps(
        {
            "transport": "workflow",
            "metadata": {"workflow_id": str(instance.id), "step": "charge_card"},
        }
    ).encode()

    await backend.replay(workflow_name="orders.saga", history=history)

    append_kwargs = backend._event_store.append.await_args.kwargs
    assert append_kwargs["payload"]["attempts_reset"] is True


@pytest.mark.asyncio
async def test_replay_rejects_unknown_instance() -> None:
    """Неизвестный инстанс → KeyError (fail-loud)."""
    backend = _build_backend(None)
    history = json.dumps({"workflow_id": str(uuid.uuid4())}).encode()

    with pytest.raises(KeyError):
        await backend.replay(workflow_name="orders.saga", history=history)


@pytest.mark.asyncio
async def test_replay_rejects_terminal_success_instance() -> None:
    """Успешно завершённый workflow переигрывать нечего → ValueError."""
    instance = _make_instance(status=WorkflowStatus.succeeded)
    backend = _build_backend(instance)
    history = json.dumps({"workflow_id": str(instance.id)}).encode()

    with pytest.raises(ValueError, match="nothing to replay"):
        await backend.replay(workflow_name="orders.saga", history=history)


@pytest.mark.asyncio
async def test_replay_rejects_malformed_history() -> None:
    """Некорректный history → ValueError (fail-loud, не silent no-op)."""
    backend = _build_backend(_make_instance())

    with pytest.raises(ValueError):
        await backend.replay(workflow_name="orders.saga", history=b"not-json")
