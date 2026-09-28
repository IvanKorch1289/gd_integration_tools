"""Compatibility shim для legacy migration tests (W2 P0-3).

Canonical: ``src.backend.dsl.engine.processors.event_store/store.py``.

Ранее здесь жил дубликат :class:`EventStore`/:class:`InMemoryEventStore`.
Теперь legacy-путь реэкспортирует canonical-реализацию, поэтому
``isinstance`` store-объектов одинаков в обоих путях импорта.
"""

from __future__ import annotations

from src.backend.dsl.engine.processors.event_store.store import EventStore as EventStore
from src.backend.dsl.engine.processors.event_store.store import (
    InMemoryEventStore as InMemoryEventStore,
)

__all__ = ("EventStore", "InMemoryEventStore")
