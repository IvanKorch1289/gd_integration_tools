"""Backward-compat shim — re-exports from :mod:`core.messaging.eventbus.facade`.

S31 Task 3: promoted to ``core/`` для архитектурной согласованности
(extensions/DSL должны получать messaging через core, не через services).
Новый код должен импортировать из ``src.backend.core.messaging.eventbus.facade``.
"""

from __future__ import annotations

from src.backend.core.messaging.eventbus.facade import (  # noqa: F401
    CapabilityChecker,
    EventBusFacade,
    get_event_bus_facade,
)

__all__ = (
    "CapabilityChecker",
    "EventBusFacade",
    "get_event_bus_facade",
)
