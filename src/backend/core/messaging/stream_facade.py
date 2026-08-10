"""Core messaging facade: StreamClient + EventBusFacade (S31 Task 3).

Promoted EventBusFacade from ``services/messaging/eventbus_facade.py`` so
extensions/DSL can access messaging через core, not services.

Entry points must import from this facade, not from infrastructure/* directly.
"""

from __future__ import annotations

# lazy __getattr__ exports verified by runtime test
from typing import Any

__all__ = (  # noqa: F822 — lazy __getattr__ export
    "EventBusFacade",
    "get_event_bus_facade",
    "get_stream_client",
)


def __getattr__(name: str) -> Any:
    if name == "get_stream_client":
        from src.backend.infrastructure.clients.messaging.stream import (
            get_stream_client,
        )

        return get_stream_client
    if name == "get_event_bus_facade":
        from src.backend.core.messaging.eventbus.facade import get_event_bus_facade

        return get_event_bus_facade
    if name == "EventBusFacade":
        from src.backend.core.messaging.eventbus.facade import EventBusFacade

        return EventBusFacade
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
