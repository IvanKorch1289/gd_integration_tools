"""S55 W3 — state.py part of pg_runner_internals decomp.

Classes: WorkflowState.
Funcs: .
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from src.backend.core.domain.models.workflow_event import WorkflowEventType
from src.backend.core.domain.models.workflow_instance import WorkflowStatus
from src.backend.infrastructure.workflow.pg_runner_internals.event_store import (
    _find_last_snapshot,
)
from src.backend.infrastructure.workflow.pg_runner_internals.rows import (
    WorkflowEventRow,
)

# ─────────────────────────────── DTO ───────────────────────────────


@dataclass(slots=True)
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
    #: Дедлайны wait-шагов (имя шага → ISO-8601). Переживают requeue,
    #: поэтому wait завершается, а не перезапускается с нового срока.
    wait_deadlines: dict[str, str] = field(default_factory=dict)

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
            wait_deadlines=dict(snapshot.get("wait_deadlines", {})),
        )

    def apply_event(
        self,
        event_type: WorkflowEventType,
        payload: dict[str, Any],
        step_name: str | None = None,
    ) -> None:
        """Применяет событие к состоянию (без чтения event log'а).

        Используется runner'ом сразу после append события — чтобы
        in-memory состояние совпадало с event log'ом (attempts,
        current_step, exchange_snapshot) без повторного replay.

        Args:
            event_type: Тип события.
            payload: Payload события.
            step_name: Имя шага (опционально).

        """
        row = WorkflowEventRow(
            seq=0,
            workflow_id=self.workflow_id,
            event_type=event_type,
            payload=dict(payload or {}),
            step_name=step_name,
            occurred_at=datetime.now(UTC),
        )
        self._apply(row)

    def _apply(self, event: WorkflowEventRow) -> None:
        """Применяет одно событие к текущему state'у (mutate in place)."""
        etype = event.event_type
        payload = event.payload or {}

        if etype == WorkflowEventType.created:
            self.workflow_name = payload.get("workflow_name", self.workflow_name)
            self.status = WorkflowStatus.pending
            # Вход workflow'а — начальный exchange: данные не теряются
            # между шагами (ADR-0394). Служебные ``__``-ключи отбрасываются.
            incoming = payload.get("input")
            if isinstance(incoming, dict):
                self.exchange_snapshot = {
                    key: value
                    for key, value in incoming.items()
                    if not str(key).startswith("__")
                }

        elif etype == WorkflowEventType.step_started:
            self.status = WorkflowStatus.running
            # attempts НЕ меняется: счётчик = число зафиксированных
            # падений (``step_failed``). Повтор после падения получает
            # тот же номер попытки и тот же idempotency-key — повтор
            # распознаваем (ADR-0394).

        elif etype == WorkflowEventType.step_finished:
            if event.step_name:
                self.step_history.append(event.step_name)
            self.current_step = int(payload.get("next_step", self.current_step + 1))
            self.attempts = 0
            exch = payload.get("exchange")
            if exch is None:
                # Legacy-события (до ADR-0394) клали результат под "output".
                exch = payload.get("output")
            if isinstance(exch, dict):
                self.exchange_snapshot = exch

        elif etype == WorkflowEventType.step_failed:
            self.last_error = str(payload.get("error", ""))[:2048]
            self.attempts = int(payload.get("attempt", self.attempts + 1))

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
            wait_step = payload.get("wait_step")
            deadline = payload.get("wait_deadline") or payload.get("next_attempt_at")
            if wait_step and deadline:
                self.wait_deadlines[str(wait_step)] = str(deadline)

        elif etype == WorkflowEventType.resumed:
            self.status = WorkflowStatus.running
            if payload.get("attempts_reset"):
                # Admin-retry: счётчик падений обнуляется — иначе
                # следующая попытка = attempts + 1 сразу превысит
                # max_attempts и workflow упадёт без единого шага
                # (ADR-0398).
                self.attempts = 0

        elif etype == WorkflowEventType.cancelled:
            self.status = WorkflowStatus.cancelled

        elif etype == WorkflowEventType.compensated:
            self.status = WorkflowStatus.compensating
