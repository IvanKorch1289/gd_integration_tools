"""Compatibility shim для legacy migration tests (W2 P0-3).

Canonical: ``src.backend.dsl.engine.processors.event_store/types.py``.

Ранее этот модуль содержал дубликат :class:`Event`/:class:`EventStream`,
из-за чего в проекте существовало два несовместимых типа ``Event``
и два независимых store-singleton. Теперь тип единственный —
legacy-путь реэкспортирует canonical-класс, поэтому
``isinstance`` работает в обоих направлениях.
"""

from __future__ import annotations

from src.backend.dsl.engine.processors.event_store.types import Event as Event
from src.backend.dsl.engine.processors.event_store.types import (
    EventStream as EventStream,
)

__all__ = ("Event", "EventStream")
