"""TDD characterization для outbox_monitor shim (Candidate #7).

BEFORE refactor — verify current behavior.
"""

from __future__ import annotations

import pytest


class TestOutboxMonitorShimProxy:
    """services/messaging/outbox_monitor.py — 5 symbols."""

    def test_all_exports(self) -> None:
        from src.backend.services.messaging.outbox_monitor import __all__

        assert set(__all__) == {
            "OutboxStuckMonitor",
            "OutboxStuckMonitorSettings",
            "default_stuck_monitor",
            "start_outbox_stuck_monitor",
            "stop_outbox_stuck_monitor",
        }

    def test_default_stuck_monitor_singleton_identity(self) -> None:
        """default_stuck_monitor — singleton, identity MUST be preserved."""
        from src.backend.services.messaging.outbox_monitor import (
            default_stuck_monitor,
        )
        from src.backend.infrastructure.messaging.outbox.stuck_monitor import (
            default_stuck_monitor as _orig,
        )

        assert default_stuck_monitor is _orig

    def test_outbox_stuck_monitor_class_identity(self) -> None:
        from src.backend.services.messaging.outbox_monitor import (
            OutboxStuckMonitor,
        )
        from src.backend.infrastructure.messaging.outbox.stuck_monitor import (
            OutboxStuckMonitor as _orig,
        )

        assert OutboxStuckMonitor is _orig

    def test_outbox_stuck_monitor_settings_class_identity(self) -> None:
        from src.backend.services.messaging.outbox_monitor import (
            OutboxStuckMonitorSettings,
        )
        from src.backend.infrastructure.messaging.outbox.stuck_monitor import (
            OutboxStuckMonitorSettings as _orig,
        )

        assert OutboxStuckMonitorSettings is _orig

    def test_start_callable(self) -> None:
        from src.backend.services.messaging.outbox_monitor import (
            start_outbox_stuck_monitor,
        )

        assert callable(start_outbox_stuck_monitor)

    def test_stop_callable(self) -> None:
        from src.backend.services.messaging.outbox_monitor import (
            stop_outbox_stuck_monitor,
        )

        assert callable(stop_outbox_stuck_monitor)

    def test_unknown_attribute_raises(self) -> None:
        from src.backend.services.messaging import outbox_monitor

        with pytest.raises(AttributeError):
            _ = outbox_monitor.__getattr__("nonexistent_xyz")
