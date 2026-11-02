"""ADR-0408 (волна 22): SLA-метрика workflow эмитится в рантайме.

Дефект (до фикса)
-----------------
``SlaTracker`` удалён как мёртвый код (ADR-0403), а чистая функция
``evaluate_sla`` не вызывалась нигде в ``src/`` — метрика
``workflow_sla_compliance_total`` была мёртвой: Grafana-дашборд и
Prometheus-алерты не имели данных (owner-задача GAP-WF-4.5).

Ожидание
--------
* при нарушении SLA-бюджета workflow счётчик
  ``workflow_sla_compliance_total{level="hard"}`` растёт;
* при соблюдении бюджета растёт ``{level="none"}``;
* без заданного бюджета метрика не эмитится (нечего оценивать);
* чистая функция ``evaluate_sla`` эмитит ту же метрику.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from prometheus_client import REGISTRY

from src.backend.core.domain.models.workflow_instance import WorkflowStatus
from src.backend.core.observability.workflow_sla import (
    WorkflowSlaLevel,
    classify_sla_breach,
    record_workflow_sla_compliance,
)
from src.backend.infrastructure.workflow.runner import (
    DurableWorkflowRunner,
    RunnerConfig,
    StepOutcome,
    StepResult,
)
from src.backend.services.workflows.sla_alerting import SlaBreachLevel, evaluate_sla

pytestmark = pytest.mark.unit

_METRIC = "workflow_sla_compliance_total"


def _sample(level: str) -> float:
    """Текущее значение счётчика по уровню (0.0 — если ещё не инкрементнут)."""
    value = REGISTRY.get_sample_value(_METRIC, {"level": level})
    return float(value) if value is not None else 0.0


def _make_instance(*, elapsed_s: float, budget_s: float | None) -> object:
    """Row инстанса с заданным «возрастом» и бюджетом времени."""
    now = datetime.now(UTC)
    payload: dict[str, object] = {}
    if budget_s is not None:
        payload["__execution_timeout_s"] = budget_s
    return type(
        "Instance",
        (),
        {
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
            "input_payload": payload,
            "created_at": now - timedelta(seconds=elapsed_s),
            "updated_at": now,
            "finished_at": None,
        },
    )()


def _build_runner() -> DurableWorkflowRunner:
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
    )


# ── Чистая классификация ──────────────────────────────────────────────


def test_classify_sla_breach_levels() -> None:
    """Классификация breach'а: none → soft → hard."""
    assert (
        classify_sla_breach(
            elapsed_seconds=10.0, soft_limit_seconds=60.0, hard_limit_seconds=300.0
        )
        is WorkflowSlaLevel.NONE
    )
    assert (
        classify_sla_breach(
            elapsed_seconds=100.0, soft_limit_seconds=60.0, hard_limit_seconds=300.0
        )
        is WorkflowSlaLevel.SOFT
    )
    assert (
        classify_sla_breach(
            elapsed_seconds=400.0, soft_limit_seconds=60.0, hard_limit_seconds=300.0
        )
        is WorkflowSlaLevel.HARD
    )


def test_sla_breach_level_alias_is_shared_with_services() -> None:
    """Services-уровень переиспользует enum из core (единый источник)."""
    assert SlaBreachLevel is WorkflowSlaLevel


# ── Метрика эмитится в рантайме (runner) ───────────────────────────────


@pytest.mark.asyncio
async def test_runner_emits_hard_breach_metric_when_budget_exceeded() -> None:
    """Workflow, превысивший SLA-бюджет, увеличивает level='hard'."""
    before = _sample("hard")
    runner = _build_runner()
    instance = _make_instance(elapsed_s=120.0, budget_s=60.0)

    await runner._apply_outcome(
        instance.id, StepResult(outcome=StepOutcome.DONE), MagicMock(), instance
    )

    assert _sample("hard") == before + 1


@pytest.mark.asyncio
async def test_runner_emits_none_level_when_budget_respected() -> None:
    """Workflow, уложившийся в бюджет, увеличивает level='none'."""
    before = _sample("none")
    runner = _build_runner()
    instance = _make_instance(elapsed_s=5.0, budget_s=60.0)

    await runner._apply_outcome(
        instance.id, StepResult(outcome=StepOutcome.DONE), MagicMock(), instance
    )

    assert _sample("none") == before + 1


@pytest.mark.asyncio
async def test_runner_emits_no_metric_without_sla_budget() -> None:
    """Без заданного бюджета SLA-метрика не эмитится."""
    before_hard = _sample("hard")
    before_none = _sample("none")
    runner = _build_runner()
    instance = _make_instance(elapsed_s=100_000.0, budget_s=None)

    await runner._apply_outcome(
        instance.id, StepResult(outcome=StepOutcome.DONE), MagicMock(), instance
    )

    assert _sample("hard") == before_hard
    assert _sample("none") == before_none


# ── Чистая функция services эмитит ту же метрику ───────────────────────


def test_evaluate_sla_emits_metric() -> None:
    """``evaluate_sla`` инкрементит счётчик по уровню breach'а."""
    before = _sample("hard")
    record = evaluate_sla(
        workflow_id="wf-sla-1",
        elapsed_seconds=400.0,
        soft_limit_seconds=60.0,
        hard_limit_seconds=300.0,
    )

    assert record.level is WorkflowSlaLevel.HARD
    assert _sample("hard") == before + 1


def test_record_workflow_sla_compliance_is_public_api() -> None:
    """Публичный helper core доступен для других вызывающих."""
    before = _sample("soft")
    record_workflow_sla_compliance(WorkflowSlaLevel.SOFT)
    assert _sample("soft") == before + 1
