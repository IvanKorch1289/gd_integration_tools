from __future__ import annotations
import threading
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, ClassVar, Protocol

from src.backend.core.logging import get_logger
from src.backend.core.types.side_effect import SideEffectKind
from src.backend.dsl.engine.processors.base import BaseProcessor, handle_processor_error

if TYPE_CHECKING:
    from src.backend.dsl.builders.base import RouteBuilder
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange

_log = get_logger(__name__)

# ── Event dataclass ─────────────────────────────────────────────────────

def get_event_store() -> EventStore:
    """Return module-level EventStore singleton."""
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                _store = InMemoryEventStore()
    return _store

def set_event_store(store: EventStore) -> None:
    """Replace module-level EventStore singleton (для tests / production)."""
    global _store
    with _store_lock:
        _store = store

def reset_event_store() -> EventStore:
    """Reset к fresh in-memory store (только для tests).

    Также очищает старый store instance (если он был singleton).
    """
    global _store
    with _store_lock:
        if _store is not None and isinstance(_store, InMemoryEventStore):
            _store._events.clear()
            _store._by_aggregate.clear()
            _store._by_stream.clear()
        _store = InMemoryEventStore()
    return _store

