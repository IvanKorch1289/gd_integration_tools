"""Durable workflow engine (event-sourcing поверх Postgres).

Пакет содержит инфраструктуру для собственного durable-workflow движка
(см. ADR-031, заменил устаревший внешний workflow-движок):

* :mod:`app.infrastructure.workflow.event_store` — append-only event API
  (:class:`WorkflowEventStore`, :class:`WorkflowEventRow`).
* :mod:`app.infrastructure.workflow.state_store` — thin CRUD для header-
  таблицы :class:`WorkflowInstance` (:class:`WorkflowInstanceStore`,
  :class:`WorkflowInstanceRow`).
* :mod:`app.infrastructure.workflow.state` — materialized
  :class:`WorkflowState` + replay (fold events).

Сценарий использования (runner в IL-WF1.2 будет комбинировать):

1. API пишет ``WorkflowInstanceStore.create(...)`` → append ``created`` →
   триггер pg_notify сигналит worker'ам.
2. Worker вызывает ``try_lock()``, читает events через ``read_events()``,
   восстанавливает :class:`WorkflowState` через ``replay()``, исполняет
   следующий шаг, пишет ``step_started``/``step_finished``.
3. На shutdown/crash — advisory lock отпускается автоматически Postgres'ом,
   другой worker подхватывает после истечения ``locked_until``.
"""

from src.backend.infrastructure.workflow.event_store import (
    WorkflowEventRow,
    WorkflowEventStore,
)
from src.backend.infrastructure.workflow.state import WorkflowState
from src.backend.infrastructure.workflow.state_store import (
    WorkflowInstanceRow,
    WorkflowInstanceStore,
)

__all__ = (
    "WorkflowEventRow",
    "WorkflowEventStore",
    "WorkflowInstanceRow",
    "WorkflowInstanceStore",
    "WorkflowState",
)
