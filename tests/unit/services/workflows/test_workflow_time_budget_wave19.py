"""Wave 19 / ADR-0396 — бюджет времени и SLA-трекинг workflow (кластер C).

Закрывает дефект (3): ``execution_timeout`` нигде не задавался, а
``SlaTracker.track()`` не имел production-callers — SLA-политика была
инертной.

Проверяется, что :class:`WorkflowFacade`:

* подставляет SLA hard-limit как ``execution_timeout`` (бюджет времени);
* регистрирует запущенный workflow в :class:`SlaTracker`;
* снимает workflow с трекинга после завершения.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest

from src.backend.core.security.capabilities import CapabilityGate, CapabilityRef
from src.backend.core.workflow import FakeWorkflowBackend
from src.backend.core.workflow.backend import WorkflowHandle
from src.backend.dsl.workflow.spec import SlaPolicy
from src.backend.services.workflows import WorkflowFacade
from src.backend.services.workflows.sla_alerting import (
    InMemorySlaAlertDispatcher,
    SlaTracker,
)

_CALLER = "ext.orders"


class _RecordingBackend(FakeWorkflowBackend):
    """Fake-backend, запоминающий переданный ``execution_timeout``."""

    def __init__(self) -> None:
        super().__init__()
        self.start_calls: list[dict[str, Any]] = []

    async def start_workflow(
        self,
        *,
        workflow_name: str,
        workflow_id: str,
        input: dict[str, Any],
        namespace: str,
        task_queue: str,
        execution_timeout: timedelta | None = None,
    ) -> WorkflowHandle:
        """Запомнить параметры старта и делегировать базовой реализации."""
        self.start_calls.append(
            {
                "workflow_name": workflow_name,
                "workflow_id": workflow_id,
                "execution_timeout": execution_timeout,
            }
        )
        return await super().start_workflow(
            workflow_name=workflow_name,
            workflow_id=workflow_id,
            input=input,
            namespace=namespace,
            task_queue=task_queue,
            execution_timeout=execution_timeout,
        )


def _facade(
    *,
    sla_policy: SlaPolicy | None = None,
) -> tuple[WorkflowFacade, _RecordingBackend, SlaTracker]:
    """Фасад с capability-gate, tracker'ом и (опционально) SLA-резолвером."""
    gate = CapabilityGate()
    gate.declare(
        _CALLER,
        [
            CapabilityRef(name="workflow.start", scope="orders.*"),
            CapabilityRef(name="workflow.signal", scope="orders.*"),
        ],
    )
    backend = _RecordingBackend()
    tracker = SlaTracker(dispatcher=InMemorySlaAlertDispatcher())
    resolver = None
    if sla_policy is not None:
        resolver = lambda _name: sla_policy  # noqa: E731 — локальный stub-резолвер
    facade = WorkflowFacade(
        backend=backend,
        capability_gate=gate,
        sla_tracker=tracker,
        sla_resolver=resolver,
    )
    return facade, backend, tracker


@pytest.mark.asyncio
async def test_sla_hard_limit_becomes_execution_timeout() -> None:
    """SLA hard-limit используется как бюджет времени workflow."""
    policy = SlaPolicy(soft_limit_seconds=10.0, hard_limit_seconds=60.0)
    facade, backend, _tracker = _facade(sla_policy=policy)

    await facade.start(
        caller=_CALLER,
        workflow_name="orders.saga",
        workflow_id="orders.42",
        input={},
        namespace="bank-a",
        task_queue="default",
    )

    assert backend.start_calls[0]["execution_timeout"] == timedelta(seconds=60.0)


@pytest.mark.asyncio
async def test_explicit_execution_timeout_wins_over_sla() -> None:
    """Явно переданный execution_timeout не перетирается SLA-политикой."""
    policy = SlaPolicy(soft_limit_seconds=10.0, hard_limit_seconds=60.0)
    facade, backend, _tracker = _facade(sla_policy=policy)

    await facade.start(
        caller=_CALLER,
        workflow_name="orders.saga",
        workflow_id="orders.42",
        input={},
        namespace="bank-a",
        task_queue="default",
        execution_timeout=timedelta(seconds=5),
    )

    assert backend.start_calls[0]["execution_timeout"] == timedelta(seconds=5)


@pytest.mark.asyncio
async def test_started_workflow_is_tracked_for_sla() -> None:
    """SlaTracker.track() получает production-call из WorkflowFacade."""
    policy = SlaPolicy(soft_limit_seconds=10.0, hard_limit_seconds=60.0)
    facade, _backend, tracker = _facade(sla_policy=policy)

    await facade.start(
        caller=_CALLER,
        workflow_name="orders.saga",
        workflow_id="orders.42",
        input={},
        namespace="bank-a",
        task_queue="default",
    )

    assert tracker.list_tracked() == ["orders.42"]


@pytest.mark.asyncio
async def test_workflow_untracked_after_completion() -> None:
    """После await_completion workflow снимается с SLA-трекинга."""
    policy = SlaPolicy(soft_limit_seconds=10.0, hard_limit_seconds=60.0)
    facade, _backend, tracker = _facade(sla_policy=policy)

    handle = await facade.start(
        caller=_CALLER,
        workflow_name="orders.saga",
        workflow_id="orders.42",
        input={},
        namespace="bank-a",
        task_queue="default",
    )
    await facade.await_completion(handle=handle)

    assert tracker.list_tracked() == []


@pytest.mark.asyncio
async def test_without_sla_no_timeout_and_no_tracking() -> None:
    """Без SLA-политики поведение не меняется (timeout=None, трекинг пуст)."""
    facade, backend, tracker = _facade()

    await facade.start(
        caller=_CALLER,
        workflow_name="orders.saga",
        workflow_id="orders.42",
        input={},
        namespace="bank-a",
        task_queue="default",
    )

    assert backend.start_calls[0]["execution_timeout"] is None
    assert tracker.list_tracked() == []
