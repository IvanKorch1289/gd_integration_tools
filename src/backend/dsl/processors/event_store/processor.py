"""Compatibility shim для legacy migration tests (W2 P0-3).

Canonical: ``src.backend.dsl.engine.processors/event_store/processor.py``.

Ранее здесь был полный дубликат :class:`EventStoreProcessor`, причём
canonical-модуль содержал stub-заглушку. Теперь реализация одна и
каноническая; legacy-импорт даёт тот же объект класса.
"""

from __future__ import annotations

from src.backend.dsl.engine.processors.event_store.processor import (
    EventStoreProcessor as EventStoreProcessor,
)

__all__ = ("EventStoreProcessor",)
