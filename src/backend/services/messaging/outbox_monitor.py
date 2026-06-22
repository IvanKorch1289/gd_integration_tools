"""OutboxStuckMonitor facade для frontend (S44 W3, ADR-0248 follow-up).

Single entry-point для in-memory read ``default_stuck_monitor`` из frontend
(Streamlit developer portal). Re-export canonical
``infrastructure.messaging.outbox.stuck_monitor`` symbols.

Использование в frontend::

    from src.backend.services.messaging.outbox_monitor import default_stuck_monitor

    count = default_stuck_monitor.last_count

Layer policy: extensions → only core. Этот facade — единственный
разрешённый путь для frontend доступа к outbox monitor'у.
См. layer-linter exception для
``services/messaging/outbox_monitor.py → infrastructure.messaging.outbox.stuck_monitor``.

S44 W3 sprint goal: закрыть последний frontend→infra import
(``96_Outbox_Stuck_Monitor.py:115``).
"""
from __future__ import annotations

from src.backend.infrastructure.messaging.outbox.stuck_monitor import (  # noqa: E402,F401
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
