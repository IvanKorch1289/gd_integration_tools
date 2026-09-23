"""CDC Control Plane Simulator (Wave 4 #34).

Проблема (DEEP_AUDIT):
    Слоты/lag/offset управляются вручную в production:
    - Publication slots: создание / удаление / list.
    - Lag: monitoring (последний LSN, lag в bytes).
    - Replay: offset management.
    - Pause / resume.
    - No unified API для этих операций.

Решение:
    ``CDCControlPlane`` — pure-Python simulator + API:

    1. ``PublicationSlot`` — create / drop / list / status.
    2. ``ReplicationLag`` — track lag в bytes и events.
    3. ``Offset`` — track LSN offset, support seek / replay.
    4. ``CDCControlPlane`` — high-level orchestrator.
    5. ``simulate_lag_growth`` — for testing dashboards.

Использование::

    from src.backend.core.cdc_control_plane import (  # noqa: F401 — re-export
        CDCControlPlane, get_cdc_control_plane,
    )

    plane = get_cdc_control_plane()
    slot = plane.create_slot("orders_pub", table="orders")
    plane.update_lag("orders_pub", bytes=1024, events=5)
    plane.pause("orders_pub")
    plane.resume("orders_pub")
    plane.replay_from("orders_pub", offset=1000)
    status = plane.get_status("orders_pub")
"""

from __future__ import annotations

from src.backend.core.cdc_control_plane.plane import (  # noqa: F401 — re-export
    CDCControlPlane,
    CDCSlotStatus,
    Offset,
    PublicationSlot,
    ReplicationLag,
    SlotStatus,
    get_cdc_control_plane,
)

__all__ = (
    "CDCControlPlane",
    "CDCSlotStatus",
    "Offset",
    "PublicationSlot",
    "ReplicationLag",
    "SlotStatus",
    "get_cdc_control_plane",
)
