"""Compatibility shim для legacy migration tests (W2 P0-3).

Canonical: ``src.backend.dsl.engine.processors.event_store/helpers.py``.

Ранее здесь был второй module-level ``EventStore``-singleton, из-за чего
``reset_event_store()`` из legacy-пути не сбрасывал store, который
использовал canonical-процессор, и наоборот. Теперь singleton один.
"""

from __future__ import annotations

from src.backend.dsl.engine.processors.event_store.helpers import (
    get_event_store as get_event_store,
)
from src.backend.dsl.engine.processors.event_store.helpers import (
    reset_event_store as reset_event_store,
)
from src.backend.dsl.engine.processors.event_store.helpers import (
    set_event_store as set_event_store,
)

__all__ = ("get_event_store", "reset_event_store", "set_event_store")
