"""Durable workflow engine (event-sourcing поверх Postgres).

Sprint 4 К3-B §3: legacy-файлы ``state.py``/``state_store.py``/
``event_store.py``/``state_projector.py`` удалены. API объединён в
:mod:`pg_runner_internals` (узкий внутренний модуль), новый стек
ориентирован на Temporal native (см. :mod:`temporal_backend`).

Public re-exports (``__init__``) сохранены для импортёров из
``runner.py`` / ``executor.py`` / ``services/workflows`` / ``schemas``.

* :class:`WorkflowEventStore` — append-only event log;
* :class:`WorkflowEventRow` — immutable DTO события;
* :class:`WorkflowInstanceStore` — CRUD header-таблицы;
* :class:`WorkflowInstanceRow` — immutable DTO header-записи;
* :class:`WorkflowState` — materialized state + replay (fold events).
"""

from src.backend.infrastructure.workflow.pg_runner_internals import (
    WorkflowEventRow,
    WorkflowEventStore,
    WorkflowInstanceRow,
    WorkflowInstanceStore,
    WorkflowState,
)

__all__ = (
    "WorkflowEventRow",
    "WorkflowEventStore",
    "WorkflowInstanceRow",
    "WorkflowInstanceStore",
    "WorkflowState",
)
