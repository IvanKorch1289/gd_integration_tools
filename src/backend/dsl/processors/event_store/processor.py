"""S66 W1 — processor.py part of event_store decomp.

EventStoreProcessor (DSL pipeline integration).

Classes: EventStoreProcessor.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any, ClassVar

from src.backend.core.logging import get_logger
from src.backend.core.types.side_effect import SideEffectKind
from src.backend.dsl.engine.processors.base import BaseProcessor, handle_processor_error
from src.backend.dsl.processors.event_store.helpers import get_event_store
from src.backend.dsl.processors.event_store.store import EventStore
from src.backend.dsl.processors.event_store.types import Event  # S66 W1: cross-import

if TYPE_CHECKING:
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange

_log = get_logger(__name__)

# ── Event dataclass ─────────────────────────────────────────────────────

from src.backend.dsl.processors.event_store.types import (
    EventStream,  # S66 W1: cross-import
)


class EventStoreProcessor(BaseProcessor):
    """Capture events from exchange, append к EventStore.

    Captures events из ``exchange.properties['events']`` (list of Event or dict)
    или ``exchange.in_message.body['events']`` (для incoming payloads с events).

    Events appended к module-level EventStore singleton (или injected).
    """

    side_effect: ClassVar[SideEffectKind] = SideEffectKind.SIDE_EFFECTING
    compensatable: ClassVar[bool] = False

    def __init__(
        self,
        *,
        stream: EventStream | str = EventStream.CUSTOM,
        event_store: EventStore | None = None,
        aggregate_id_field: str = "aggregate_id",
        events_field: str = "events",
        event_type_field: str = "event_type",
        name: str | None = None,
    ) -> None:
        if isinstance(stream, str) and stream not in [s.value for s in EventStream]:
            raise ValueError(
                f"stream должен быть EventStream или known value, получено {stream!r}"
            )
        super().__init__(name=name or f"event_store_{stream}")
        self._stream = EventStream(stream) if isinstance(stream, str) else stream
        self._store: EventStore = event_store or get_event_store()
        self._aggregate_id_field = aggregate_id_field
        self._events_field = events_field
        self._event_type_field = event_type_field

    @handle_processor_error
    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Capture events из body[events_field] или properties[events_field]."""
        # Source 1: exchange.properties['events']
        events_raw = exchange.properties.get(self._events_field)
        # Source 2: exchange.in_message.body[events_field]
        if events_raw is None:
            body = exchange.in_message.body
            if isinstance(body, dict):
                events_raw = body.get(self._events_field)

        if not events_raw:
            return  # no events → no-op

        if not isinstance(events_raw, list):
            raise TypeError(
                f"{self._events_field} должен быть list, "
                f"получено {type(events_raw).__name__}"
            )

        for ev_raw in events_raw:
            if isinstance(ev_raw, Event):
                self._store.append(ev_raw)
            elif isinstance(ev_raw, dict):
                # Auto-convert dict → Event
                aggregate_id = ev_raw.get(self._aggregate_id_field, str(uuid.uuid4()))
                event_type = ev_raw.get(self._event_type_field, "unknown")
                payload = {
                    k: v
                    for k, v in ev_raw.items()
                    if k
                    not in (
                        self._aggregate_id_field,
                        self._event_type_field,
                        "event_id",
                        "version",
                        "timestamp",
                    )
                }
                self._store.append(
                    Event(
                        aggregate_id=aggregate_id,
                        event_type=event_type,
                        stream=self._stream,
                        payload=payload,
                    )
                )
            else:
                raise TypeError(
                    f"event должен быть Event или dict, "
                    f"получено {type(ev_raw).__name__}"
                )

        # Record count в exchange properties
        exchange.set_property("events_appended", len(events_raw))
