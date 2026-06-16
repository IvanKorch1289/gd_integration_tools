"""Event store + CQRS package (S66 W1 decomp from event_store.py 468 LOC).

9 classes + 3 funcs → 5 files (per-concern):
- ``types.py``: EventStream, Event (2 data types)
- ``store.py``: EventStore (ABC) + InMemoryEventStore (impl)
- ``cqrs.py``: Projection, CommandBus, QueryBus, CQRSMixin (4 CQRS classes)
- ``processor.py``: EventStoreProcessor (DSL integration)
- ``helpers.py``: 3 module-level funcs (get/set/reset)

Backward-compat: ``from src.backend.dsl.processors.event_store import EventStore`` works.
"""

from __future__ import annotations

from src.backend.dsl.processors.event_store.cqrs import (
    CommandBus,  # S66 W1: re-export
    CQRSMixin,  # S66 W1: re-export
    Projection,  # S66 W1: re-export
    QueryBus,  # S66 W1: re-export
)
from src.backend.dsl.processors.event_store.helpers import (
    get_event_store,  # S66 W1: helper re-export
    reset_event_store,  # S66 W1: helper re-export
    set_event_store,  # S66 W1: helper re-export
)
from src.backend.dsl.processors.event_store.processor import (
    EventStoreProcessor,  # S66 W1: re-export
)
from src.backend.dsl.processors.event_store.store import (
    EventStore,  # S66 W1: re-export
    InMemoryEventStore,  # S66 W1: re-export
)
from src.backend.dsl.processors.event_store.types import (
    Event,  # S66 W1: re-export
    EventStream,  # S66 W1: re-export
)

__all__ = (
    "EventStream",
    "Event",
    "EventStore",
    "InMemoryEventStore",
    "Projection",
    "CommandBus",
    "QueryBus",
    "EventStoreProcessor",
    "CQRSMixin",
    "get_event_store",
    "set_event_store",
    "reset_event_store",
)
