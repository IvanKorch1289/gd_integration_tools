"""S55 W3 — rows.py part of pg_runner_internals decomp.

Classes: WorkflowEventRow, WorkflowInstanceRow.
Funcs: .
"""

from __future__ import annotations

"""Внутренние store-helpers для workflow-стека (Sprint 4 К3-B §3).

Объединяет API, ранее разнесённое по 4 deprecated-модулям
(``state.py`` / ``state_store.py`` / ``event_store.py`` /
``state_projector.py``). Минимально-достаточный набор, необходимый:

* :class:`PgRunnerWorkflowBackend` — узкий create/get/cancel/await-completion
  адаптер поверх Postgres backend'а;
* :class:`DurableWorkflowRunner` (``runner.py``) — orchestration loop:
  ``list_pending``/``try_lock``/``read_events``/``replay`` →
  ``WorkflowState`` → ``append`` → ``unlock``;
* :class:`DSLStepExecutor` (``executor.py``) — пользуется
  ``WorkflowState.replay`` для resume-after-crash сценариев.

Sprint 4 К3-B §3 — удалены 4 legacy-файла (985 LOC), Mongo-проекция
(``state_projector.py``) убрана без замены: новый стек идёт на Temporal
native (см. :mod:`temporal_backend`), pg_runner оставлен legacy fallback.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from src.backend.infrastructure.database.models.workflow_event import (
    WorkflowEvent,
    WorkflowEventType,
)
from src.backend.infrastructure.database.models.workflow_instance import (
    WorkflowInstance,
    WorkflowStatus,
)
from src.backend.infrastructure.logging.factory import get_logger

_logger = get_logger("workflow.pg_runner_internals")

# ─────────────────────────────── DTO ───────────────────────────────


@dataclass(slots=True, frozen=True)
class WorkflowEventRow:
    """Immutable DTO одной строки event log'а.

    Использование DTO (а не ORM-объекта) делает API независимым от
    сессии — row можно хранить, передавать между корутинами и т.п.
    """

    seq: int
    workflow_id: UUID
    event_type: WorkflowEventType
    payload: dict[str, Any]
    step_name: str | None
    occurred_at: datetime

    @classmethod
    def from_orm(cls, obj: WorkflowEvent) -> WorkflowEventRow:
        """Создаёт DTO из ORM-объекта."""
        return cls(
            seq=int(obj.id),
            workflow_id=obj.workflow_id,
            event_type=obj.event_type,
            payload=dict(obj.payload or {}),
            step_name=obj.step_name,
            occurred_at=obj.occurred_at,
        )


class WorkflowInstanceRow:
    """Immutable DTO header-записи workflow инстанса."""

    id: UUID
    workflow_name: str
    route_id: str
    status: WorkflowStatus
    current_version: int
    last_event_seq: int | None
    snapshot_state: dict[str, Any] | None
    next_attempt_at: datetime | None
    locked_by: str | None
    locked_until: datetime | None
    tenant_id: str
    input_payload: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    finished_at: datetime | None

    @classmethod
    def from_orm(cls, obj: WorkflowInstance) -> WorkflowInstanceRow:
        """Создаёт DTO из ORM-объекта."""
        return cls(
            id=obj.id,
            workflow_name=obj.workflow_name,
            route_id=obj.route_id,
            status=obj.status,
            current_version=int(obj.current_version),
            last_event_seq=(
                int(obj.last_event_seq) if obj.last_event_seq is not None else None
            ),
            snapshot_state=(dict(obj.snapshot_state) if obj.snapshot_state else None),
            next_attempt_at=obj.next_attempt_at,
            locked_by=obj.locked_by,
            locked_until=obj.locked_until,
            tenant_id=obj.tenant_id,
            input_payload=dict(obj.input_payload or {}),
            created_at=obj.created_at,
            updated_at=obj.updated_at,
            finished_at=obj.finished_at,
        )
