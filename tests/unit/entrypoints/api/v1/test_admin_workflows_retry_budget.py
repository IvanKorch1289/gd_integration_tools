"""Wave 20 / ADR-0398 — admin-retry сбрасывает retry-бюджет workflow.

Регрессия: ``POST /admin/workflows/{id}/retry`` менял только статус
инстанса. Счётчик падений в event log'е оставался равным 11, поэтому
``next_attempt = attempts + 1`` сразу превышал ``max_attempts`` и workflow
падал снова, не выполнив ни одного шага.
"""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest
from fastapi import HTTPException

from src.backend.core.domain.models.workflow_event import WorkflowEventType
from src.backend.core.domain.models.workflow_instance import WorkflowStatus
from src.backend.entrypoints.api.v1.endpoints.admin_workflows import facade
from src.backend.infrastructure.workflow.executor.state import next_attempt
from src.backend.infrastructure.workflow.pg_runner_internals import (
    WorkflowEventRow,
    WorkflowInstanceRow,
    WorkflowState,
)

# ── Fakes ───────────────────────────────────────────────────────────


class FakeInstanceStore:
    """Минимальный instance store для facade."""

    def __init__(self, instance: WorkflowInstanceRow) -> None:
        """Инициализация стора одним инстансом."""
        self.instance = instance
        self.status_updates: list[WorkflowStatus] = []

    async def get(self, workflow_id: UUID) -> WorkflowInstanceRow | None:
        """Вернуть header инстанса."""
        return self.instance

    async def update_status(
        self,
        workflow_id: UUID,
        status: WorkflowStatus,
        next_attempt_at: datetime | None = None,
        error: str | None = None,
    ) -> None:
        """Обновить статус инстанса."""
        self.status_updates.append(status)
        self.instance = replace(self.instance, status=status)


class FakeEventStore:
    """Минимальный event store для facade."""

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
        """Дописать событие в лог."""
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


def make_instance(status: WorkflowStatus) -> WorkflowInstanceRow:
    """Создать header-строку инстанса."""
    now = datetime.now(UTC)
    return WorkflowInstanceRow(
        id=uuid.uuid4(),
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


# ── Тесты ───────────────────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_admin_retry_resets_retry_budget(monkeypatch: Any) -> None:
    """Retry сбрасывает счётчик падений — workflow можно восстановить."""
    instance = make_instance(WorkflowStatus.failed)
    store = FakeInstanceStore(instance)
    event_store = FakeEventStore()
    monkeypatch.setattr(facade, "_instance_store", lambda: store)
    monkeypatch.setattr(facade, "_event_store", lambda: event_store)

    # Event log до retry: workflow падал 11 раз подряд.
    await event_store.append(
        instance.id,
        WorkflowEventType.created,
        {"workflow_name": "wf-test", "route_id": "r-1", "input": {}},
        None,
    )
    await event_store.append(
        instance.id,
        WorkflowEventType.step_failed,
        {"error": "boom", "attempt": 11, "reason": "max_attempts_exceeded"},
        "s1",
    )
    state_before = WorkflowState.replay(event_store.events)
    assert state_before.attempts == 11

    result = await facade._get_facade().retry_workflow(instance_id=instance.id)

    assert result["status"] == "accepted"
    assert result["new_status"] == WorkflowStatus.pending.value
    assert store.status_updates == [WorkflowStatus.pending]

    # В event log'е появилось событие retry, обнуляющее бюджет.
    retry_events = [
        e for e in event_store.events if e.event_type == WorkflowEventType.resumed
    ]
    assert len(retry_events) == 1
    assert retry_events[0].payload["attempts_reset"] is True

    state_after = WorkflowState.replay(event_store.events)
    assert state_after.attempts == 0
    assert next_attempt(state_after) == 1, "следующая попытка должна быть первой"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_admin_retry_rejects_terminal_status(monkeypatch: Any) -> None:
    """Успешный workflow ретраить нельзя (409)."""
    instance = make_instance(WorkflowStatus.succeeded)
    store = FakeInstanceStore(instance)
    event_store = FakeEventStore()
    monkeypatch.setattr(facade, "_instance_store", lambda: store)
    monkeypatch.setattr(facade, "_event_store", lambda: event_store)

    with pytest.raises(HTTPException) as exc_info:
        await facade._get_facade().retry_workflow(instance_id=instance.id)

    assert exc_info.value.status_code == 409
    assert event_store.events == []
