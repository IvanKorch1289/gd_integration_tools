"""S55 W3 — state.py part of pg_runner_internals decomp.

Classes: WorkflowState.
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

from dataclasses import asdict, dataclass, field
from typing import Any
from uuid import UUID

from src.backend.core.domain.models.workflow_event import WorkflowEventType
from src.backend.core.domain.models.workflow_instance import WorkflowStatus
from src.backend.infrastructure.logging.factory import get_logger

_logger = get_logger("workflow.pg_runner_internals")

# ─────────────────────────────── DTO ───────────────────────────────


@dataclass(slots=True, frozen=True)
class WorkflowState:
    """Materialized state workflow инстанса.

    Fold поверх event log'а через :meth:`replay`. Чистая функция от
    events → state.
    """

    workflow_id: UUID
    workflow_name: str = ""
    current_step: int = 0
    step_history: list[str] = field(default_factory=list)
    branch_choices: dict[str, str] = field(default_factory=dict)
    loop_counters: dict[str, int] = field(default_factory=dict)
    exchange_snapshot: dict[str, Any] = field(default_factory=dict)
    attempts: int = 0
    status: WorkflowStatus = WorkflowStatus.pending
    last_error: str | None = None
    child_workflows: list[str] = field(default_factory=list)

    @classmethod
    def replay(cls, events: list[WorkflowEventRow]) -> WorkflowState:
        """Fold событий в текущее состояние.

        Если среди событий встречается ``snapshotted``, стартуем с
        последнего snapshot'а и применяем только последующие события.

        Args:
            events: Список событий в порядке возрастания ``seq``.

        Returns:
            Materialized :class:`WorkflowState`.

        Raises:
            ValueError: Если передан пустой список или первое событие
                без snapshot'а не ``created``.
        """
        if not events:
            raise ValueError("cannot replay empty event list")

        snapshot_index = _find_last_snapshot(events)

        if snapshot_index is not None:
            snap_event = events[snapshot_index]
            state = cls._from_snapshot_payload(
                workflow_id=snap_event.workflow_id,
                snapshot=snap_event.payload.get("state", {}),
            )
            tail = events[snapshot_index + 1 :]
        else:
            first = events[0]
            if first.event_type != WorkflowEventType.created:
                raise ValueError(
                    "first event without snapshot must be 'created', "
                    f"got {first.event_type!r}"
                )
            state = cls(
                workflow_id=first.workflow_id,
                workflow_name=first.payload.get("workflow_name", ""),
            )
            state._apply(first)
            tail = events[1:]

        for ev in tail:
            state._apply(ev)
        return state

    @classmethod
    def replay_from_snapshot(
        cls,
        workflow_id: UUID,
        snapshot: dict[str, Any],
        tail_events: list[WorkflowEventRow],
    ) -> WorkflowState:
        """Rebuild state из snapshot'а + хвоста событий."""
        state = cls._from_snapshot_payload(workflow_id, snapshot)
        for ev in tail_events:
            state._apply(ev)
        return state

    def to_snapshot(self) -> dict[str, Any]:
        """Сериализует state в JSON-совместимый dict для ``snapshot``'а."""
        raw = asdict(self)
        raw["workflow_id"] = str(self.workflow_id)
        raw["status"] = self.status.value
        return raw

    @classmethod
    def _from_snapshot_payload(
        cls, workflow_id: UUID, snapshot: dict[str, Any]
    ) -> WorkflowState:
        """Восстанавливает state из результата :meth:`to_snapshot`."""
        status_raw = snapshot.get("status", WorkflowStatus.pending.value)
        try:
            status = WorkflowStatus(status_raw)
        except ValueError:
            status = WorkflowStatus.pending

        return cls(
            workflow_id=workflow_id,
            workflow_name=snapshot.get("workflow_name", ""),
            current_step=int(snapshot.get("current_step", 0)),
            step_history=list(snapshot.get("step_history", [])),
            branch_choices=dict(snapshot.get("branch_choices", {})),
            loop_counters=dict(snapshot.get("loop_counters", {})),
            exchange_snapshot=dict(snapshot.get("exchange_snapshot", {})),
            attempts=int(snapshot.get("attempts", 0)),
            status=status,
            last_error=snapshot.get("last_error"),
            child_workflows=list(snapshot.get("child_workflows", [])),
        )

    def _apply(self, event: WorkflowEventRow) -> None:
        """Применяет одно событие к текущему state'у (mutate in place)."""
        etype = event.event_type
        payload = event.payload or {}

        if etype == WorkflowEventType.created:
            self.workflow_name = payload.get("workflow_name", self.workflow_name)
            self.status = WorkflowStatus.pending

        elif etype == WorkflowEventType.step_started:
            self.status = WorkflowStatus.running
            self.attempts = int(payload.get("attempt", self.attempts + 1))

        elif etype == WorkflowEventType.step_finished:
            if event.step_name:
                self.step_history.append(event.step_name)
            self.current_step = int(payload.get("next_step", self.current_step + 1))
            self.attempts = 0
            exch = payload.get("exchange")
            if isinstance(exch, dict):
                self.exchange_snapshot = exch

        elif etype == WorkflowEventType.step_failed:
            self.last_error = str(payload.get("error", ""))[:2048]
            self.attempts = int(payload.get("attempt", self.attempts))

        elif etype == WorkflowEventType.branch_taken:
            name = payload.get("choice", event.step_name or "")
            branch = payload.get("branch", "")
            if name:
                self.branch_choices[name] = branch

        elif etype == WorkflowEventType.loop_iter:
            name = payload.get("loop", event.step_name or "")
            if name:
                self.loop_counters[name] = self.loop_counters.get(name, 0) + 1

        elif etype == WorkflowEventType.sub_spawned:
            child = payload.get("child_workflow_id")
            if child:
                self.child_workflows.append(str(child))

        elif etype == WorkflowEventType.paused:
            self.status = WorkflowStatus.paused

        elif etype == WorkflowEventType.resumed:
            self.status = WorkflowStatus.running

        elif etype == WorkflowEventType.cancelled:
            self.status = WorkflowStatus.cancelled

        elif etype == WorkflowEventType.compensated:
            self.status = WorkflowStatus.compensating
