# DEPRECATED V16 Sprint 1 — будет удалён после Single-Entry refactor финала.
# Temporal native (infrastructure/workflow/temporal_*) заменяет state-machine.
# См. PLAN.md V16 §4 Sprint 1 Workflow Single-Entry refactor.
"""Materialized state durable workflow — fold поверх event log'а.

:class:`WorkflowState` — dataclass, отображающий текущее состояние
инстанса. Главный метод — :meth:`replay` — принимает список событий
и фолдит их в текущее состояние.

Контракт:
    * Если последним событием в серии был ``snapshotted``, метод
      ``replay_from_snapshot`` стартует с закэшированного state'а и
      применяет только хвост событий после snapshot'а.
    * Fold — чистая функция от events → state. Никаких побочных эффектов.
    * Unknown ``event_type`` — логируется и игнорируется (forward-compat
      для новых типов событий).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any
from uuid import UUID

from src.backend.infrastructure.database.models.workflow_event import WorkflowEventType
from src.backend.infrastructure.database.models.workflow_instance import WorkflowStatus
from src.backend.infrastructure.workflow.event_store import WorkflowEventRow

__all__ = ("WorkflowState",)


@dataclass
class WorkflowState:
    """Materialized state workflow инстанса.

    Attributes:
        workflow_id: UUID инстанса.
        workflow_name: Логическое имя workflow.
        current_step: Индекс текущего шага в DSL pipeline'е.
        step_history: Список имён успешно выполненных шагов (FIFO).
        branch_choices: Карта ``{choice_name: taken_branch}`` для ветвлений.
        loop_counters: Карта ``{loop_name: iteration_count}`` для циклов.
        exchange_snapshot: Последний известный ``Exchange.body + properties``
            для передачи между шагами при resume после crash.
        attempts: Счётчик попыток текущего шага (для retry budget).
        status: Текущий логический статус (дублирует header для
            автономности state'а).
        last_error: Текст последней ошибки (для UI / post-mortem).
        child_workflows: Список UUID дочерних workflows, запущенных через
            ``sub_spawned``.
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

    # --- fold --------------------------------------------------------------

    @classmethod
    def replay(cls, events: list[WorkflowEventRow]) -> "WorkflowState":
        """Fold событий в текущее состояние.

        Если среди событий встречается ``snapshotted``, стартуем с
        последнего snapshot'а и применяем только последующие события
        (оптимизация — не перечитываем предыдущие шаги).

        Args:
            events: Список событий в порядке возрастания ``seq``.

        Returns:
            Materialized :class:`WorkflowState`.

        Raises:
            ValueError: Если передан пустой список (нельзя определить
                workflow_id) или если первое событие не ``created`` и
                нет snapshot'а.
        """
        if not events:
            raise ValueError("cannot replay empty event list")

        # Ищем последний snapshotted — если есть, стартуем с него.
        snapshot_index = _find_last_snapshot(events)

        if snapshot_index is not None:
            snap_event = events[snapshot_index]
            state = cls._from_snapshot_payload(
                workflow_id=snap_event.workflow_id,
                snapshot=snap_event.payload.get("state", {}),
            )
            tail = events[snapshot_index + 1 :]
        else:
            # Без snapshot'а — первое событие должно быть 'created'.
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
    ) -> "WorkflowState":
        """Rebuild state из snapshot'а + хвоста событий.

        Используется runner'ом, когда snapshot кэширован в
        ``workflow_instances.snapshot_state`` и читать полный log не нужно.
        """
        state = cls._from_snapshot_payload(workflow_id, snapshot)
        for ev in tail_events:
            state._apply(ev)
        return state

    # --- snapshot serialization -------------------------------------------

    def to_snapshot(self) -> dict[str, Any]:
        """Сериализует state в JSON-совместимый dict для ``snapshot``'а."""
        raw = asdict(self)
        raw["workflow_id"] = str(self.workflow_id)
        raw["status"] = self.status.value
        return raw

    @classmethod
    def _from_snapshot_payload(
        cls, workflow_id: UUID, snapshot: dict[str, Any]
    ) -> "WorkflowState":
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

    # --- event application ------------------------------------------------

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

        elif etype == WorkflowEventType.sub_completed:
            # Ничего не вычищаем — список дочерних нужен для аудита.
            pass

        elif etype == WorkflowEventType.paused:
            self.status = WorkflowStatus.paused

        elif etype == WorkflowEventType.resumed:
            self.status = WorkflowStatus.running

        elif etype == WorkflowEventType.cancelled:
            self.status = WorkflowStatus.cancelled

        elif etype == WorkflowEventType.compensated:
            self.status = WorkflowStatus.compensating

        elif etype == WorkflowEventType.snapshotted:
            # Snapshot event сам по себе не меняет state (он — метка
            # компакции); реальная десериализация происходит в
            # replay() при обнаружении последнего snapshot'а.
            pass

        # Unknown event_type — forward-compat, игнорируем.


def _find_last_snapshot(events: list[WorkflowEventRow]) -> int | None:
    """Возвращает индекс последнего ``snapshotted`` события или ``None``."""
    for idx in range(len(events) - 1, -1, -1):
        if events[idx].event_type == WorkflowEventType.snapshotted:
            return idx
    return None
