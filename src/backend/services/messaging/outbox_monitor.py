"""OutboxStuckMonitor facade для frontend (S44 W3 + Sprint 224 lazy proxy).

Single entry-point для in-memory read ``default_stuck_monitor`` из frontend
(Streamlit developer portal). Re-export canonical
``infrastructure.messaging.outbox.stuck_monitor`` symbols.

Sprint 224 refactor: convert direct re-export to ``__getattr__``-based lazy
proxy (ponytail: thin proxy). Устраняет layer-violation
``services → infrastructure``.

Использование в frontend::

    from src.backend.services.messaging.outbox_monitor import default_stuck_monitor

    count = default_stuck_monitor.last_count

Layer policy: extensions → only core. Этот facade — единственный
разрешённый путь для frontend доступа к outbox monitor'у.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.backend.infrastructure.messaging.outbox.stuck_monitor import (
        OutboxStuckMonitor,
        OutboxStuckMonitorSettings,
        default_stuck_monitor,
        start_outbox_stuck_monitor,
        stop_outbox_stuck_monitor,
    )

__all__ = (
    "OutboxStuckMonitor",
    "OutboxStuckMonitorSettings",
    "default_stuck_monitor",
    "start_outbox_stuck_monitor",
    "stop_outbox_stuck_monitor",
)


def __getattr__(name: str) -> Any:
    """Lazy proxy: импорт infrastructure только при lookup атрибута.

    Для ``default_stuck_monitor`` (singleton) — proxy сохраняет identity
    через атрибутный lookup, который кэшируется в module namespace
    infrastructure.messaging.outbox.stuck_monitor.
    """
    if name in {
        "OutboxStuckMonitor",
        "OutboxStuckMonitorSettings",
        "default_stuck_monitor",
        "start_outbox_stuck_monitor",
        "stop_outbox_stuck_monitor",
    }:
        from src.backend.core.api.messaging import stuck_monitor as _m

        return getattr(_m, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
