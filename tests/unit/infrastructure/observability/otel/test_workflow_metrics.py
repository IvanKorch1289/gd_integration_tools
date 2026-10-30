"""ADR-0399 — workflow-метрики pg-runner'а (OTel).

Дефект (5, medium): метрики workflow были объявлены в
``infrastructure/observability/otel/setup.py``, но ни одна ``record``
не вызывалась — в pg-runner не было метрик шага/ретрая/компенсации.

Проверяем:
* recorders пишут в OTel-инструменты с ожидаемыми именами и значениями;
* pg-runner (DurableWorkflowRunner) эмитит step_duration / step_retries /
  compensation_total / workflow_status.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.backend.core.domain.models.workflow_event import WorkflowEventType
from src.backend.core.domain.models.workflow_instance import WorkflowStatus
from src.backend.infrastructure.observability.otel import setup as otel_setup
from src.backend.infrastructure.workflow import runner as runner_module
from src.backend.infrastructure.workflow.executor.state import StepDescriptor
from src.backend.infrastructure.workflow.pg_runner_internals import WorkflowInstanceRow
from src.backend.infrastructure.workflow.runner import (
    DurableWorkflowRunner,
    RunnerConfig,
    StepOutcome,
    StepResult,
)


class _FakeInstrument:
    """Заглушка OTel-инструмента (histogram/counter)."""

    def __init__(self, name: str, kind: str) -> None:
        """Создать инструмент с именем и типом."""
        self.name = name
        self.kind = kind
        self.values: list[tuple[float, dict[str, Any]]] = []

    def record(self, amount: float, attributes: dict[str, Any] | None = None) -> None:
        """Записать значение (histogram)."""
        self.values.append((amount, dict(attributes or {})))

    def add(self, amount: float, attributes: dict[str, Any] | None = None) -> None:
        """Добавить значение (counter)."""
        self.values.append((amount, dict(attributes or {})))


class _FakeMeter:
    """Заглушка OTel-meter: создаёт ``_FakeInstrument``."""

    def __init__(self) -> None:
        """Создать пустой meter."""
        self.instruments: dict[str, _FakeInstrument] = {}

    def create_histogram(self, name: str, **kwargs: Any) -> _FakeInstrument:
        """Создать histogram."""
        return self._create(name, "histogram")

    def create_counter(self, name: str, **kwargs: Any) -> _FakeInstrument:
        """Создать counter."""
        return self._create(name, "counter")

    def _create(self, name: str, kind: str) -> _FakeInstrument:
        instrument = self.instruments.get(name)
        if instrument is None:
            instrument = _FakeInstrument(name, kind)
            self.instruments[name] = instrument
        return instrument


@pytest.fixture
def fake_meter(monkeypatch: pytest.MonkeyPatch) -> _FakeMeter:
    """Подменить OTel-meter на заглушку + сбросить кэш инструментов."""
    meter = _FakeMeter()
    monkeypatch.setattr(otel_setup, "_workflow_instruments", {})
    monkeypatch.setattr("opentelemetry.metrics.get_meter", lambda *_a, **_kw: meter)
    return meter


@pytest.mark.unit
class TestWorkflowMetricRecorders:
    """Recorders пишут в OTel-инструменты."""

    def test_step_duration_recorded(self, fake_meter: _FakeMeter) -> None:
        """Длительность шага → histogram ``workflow.step_duration``."""
        otel_setup.record_workflow_step_duration(
            workflow_name="wf", step_name="charge", duration_ms=12.5, outcome="continue"
        )

        instrument = fake_meter.instruments[otel_setup.WORKFLOW_STEP_DURATION]
        assert instrument.kind == "histogram"
        amount, attributes = instrument.values[0]
        assert amount == pytest.approx(12.5)
        assert attributes["workflow_name"] == "wf"
        assert attributes["step_name"] == "charge"
        assert attributes["outcome"] == "continue"

    def test_step_retries_recorded(self, fake_meter: _FakeMeter) -> None:
        """Ретраи шага → counter ``workflow.step_retries``."""
        otel_setup.record_workflow_step_retries(
            workflow_name="wf", step_name="charge", retries=2
        )

        instrument = fake_meter.instruments[otel_setup.WORKFLOW_STEP_RETRIES]
        assert instrument.kind == "counter"
        amount, attributes = instrument.values[0]
        assert amount == 2
        assert attributes["step_name"] == "charge"

    def test_zero_retries_not_recorded(self, fake_meter: _FakeMeter) -> None:
        """Нулевые ретраи не эмитятся (нет шума в метрике)."""
        otel_setup.record_workflow_step_retries(
            workflow_name="wf", step_name="charge", retries=0
        )

        assert otel_setup.WORKFLOW_STEP_RETRIES not in fake_meter.instruments

    def test_compensation_recorded(self, fake_meter: _FakeMeter) -> None:
        """Компенсации → counter ``workflow.compensation_total``."""
        otel_setup.record_workflow_compensation(
            workflow_name="wf", status="completed", steps=2
        )

        instrument = fake_meter.instruments[otel_setup.WORKFLOW_COMPENSATION_TOTAL]
        amount, attributes = instrument.values[0]
        assert amount == 2
        assert attributes["status"] == "completed"

    def test_workflow_status_recorded(self, fake_meter: _FakeMeter) -> None:
        """Статус workflow → counter ``workflow.status``."""
        otel_setup.record_workflow_status(workflow_name="wf", status="succeeded")

        instrument = fake_meter.instruments[otel_setup.WORKFLOW_STATUS]
        amount, attributes = instrument.values[0]
        assert amount == 1
        assert attributes["status"] == "succeeded"

    def test_recorders_are_noop_without_otel(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Без OTel API recorders не падают (no-op)."""
        monkeypatch.setattr(otel_setup, "_workflow_instruments", {})

        real_import = __import__

        def _fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
            if name == "opentelemetry":
                raise ImportError("no otel")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr("builtins.__import__", _fake_import)
        otel_setup.record_workflow_status(workflow_name="wf", status="succeeded")


def _make_instance() -> WorkflowInstanceRow:
    """Собрать DTO workflow-инстанса для runner'а."""
    now = datetime.now(UTC)
    return WorkflowInstanceRow(
        id=uuid.uuid4(),
        workflow_name="wf-metrics",
        route_id="r-1",
        status=WorkflowStatus.running,
        current_version=1,
        last_event_seq=None,
        snapshot_state=None,
        next_attempt_at=None,
        locked_by="test-worker",
        locked_until=now,
        tenant_id="t-1",
        input_payload={},
        created_at=now,
        updated_at=now,
        finished_at=None,
    )


def _build_runner(
    instance: WorkflowInstanceRow, result: StepResult
) -> tuple[DurableWorkflowRunner, MagicMock]:
    """Runner с mock-хранилищами и заданным результатом executor'а."""
    config = RunnerConfig(worker_id="test-worker", max_concurrent=1)
    state_store = MagicMock(name="state_store")
    state_store.update_status = AsyncMock(name="update_status")
    state_store.try_lock = AsyncMock(name="try_lock", return_value=True)
    state_store.get = AsyncMock(name="get", return_value=instance)
    state_store.unlock = AsyncMock(name="unlock", return_value=True)
    event_store = MagicMock(name="event_store")
    event_store.read_events = AsyncMock(name="read_events", return_value=[])
    event_store.append = AsyncMock(name="append", return_value=1)
    event_store.snapshot = AsyncMock(name="snapshot")
    executor = MagicMock(name="executor")
    executor.describe_next = MagicMock(
        return_value=StepDescriptor(name="charge", kind="sequential", attempt=2)
    )
    executor.execute_next = AsyncMock(return_value=result)
    runner = DurableWorkflowRunner(
        config=config,
        executor=executor,
        state_store=state_store,
        event_store=event_store,
        listener_dsn=None,
    )
    return runner, executor


@pytest.mark.unit
@pytest.mark.asyncio
class TestPgRunnerEmitsMetrics:
    """pg-runner эмитит workflow-метрики."""

    async def test_step_metrics_are_emitted(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Длительность/ретраи/компенсации/статус — из одного шага."""
        calls: dict[str, Any] = {}
        for name in (
            "record_workflow_step_duration",
            "record_workflow_step_retries",
            "record_workflow_compensation",
            "record_workflow_status",
        ):
            monkeypatch.setattr(
                runner_module,
                name,
                (lambda _n: lambda **kwargs: calls.__setitem__(_n, kwargs))(name),
            )

        instance = _make_instance()
        result = StepResult(
            outcome=StepOutcome.DONE,
            events=[
                (
                    WorkflowEventType.compensated,
                    {"status": "completed", "steps": ["rollback"]},
                    None,
                )
            ],
        )
        runner, _executor = _build_runner(instance, result)

        await runner._run_step(instance.id)

        duration = calls["record_workflow_step_duration"]
        assert duration["workflow_name"] == "wf-metrics"
        assert duration["step_name"] == "charge"
        assert duration["duration_ms"] >= 0.0
        assert duration["outcome"] == StepOutcome.DONE

        retries = calls["record_workflow_step_retries"]
        assert retries["retries"] == 1
        assert retries["step_name"] == "charge"

        compensation = calls["record_workflow_compensation"]
        assert compensation["steps"] == 1
        assert compensation["status"] == "completed"

        status = calls["record_workflow_status"]
        assert status["status"] == "succeeded"
        assert status["workflow_name"] == "wf-metrics"
