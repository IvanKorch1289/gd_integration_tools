"""CDC Control Plane — pure-Python simulator + API (Wave 4 #34).

Models the operations of PostgreSQL logical replication control plane:
- publication slots (create / drop / list / status).
- replication lag monitoring.
- offset management + replay.
- pause / resume.

Pure-Python: no PG, no replication required. Production → real PG replication
API (pg_replication_slots, pg_stat_replication).
"""

from __future__ import annotations

import enum
import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

__all__ = (
    "CDCControlPlane",
    "CDCSlotStatus",
    "Offset",
    "PublicationSlot",
    "ReplicationLag",
    "SlotStatus",
    "get_cdc_control_plane",
)


class SlotStatus(str, enum.Enum):
    """Status of a replication slot."""

    ACTIVE = "active"
    PAUSED = "paused"
    FAILED = "failed"
    DROPPED = "dropped"


class CDCSlotStatus(str, enum.Enum):
    """Alias for SlotStatus (public API)."""

    ACTIVE = "active"
    PAUSED = "paused"
    FAILED = "failed"
    DROPPED = "dropped"


@dataclass(slots=True)
class Offset:
    """LSN-style offset.

    Attributes:
        value: Numeric offset (e.g., LSN as integer).
        event_id: Optional event identifier (e.g., transaction ID).
        timestamp: Wall-clock time of offset capture.
    """

    value: int = 0
    event_id: str | None = None
    timestamp: float = 0.0

    @classmethod
    def now(cls, value: int = 0) -> "Offset":
        """Создать Offset из значения (конструктор-хелпер)."""
        return cls(value=value, timestamp=time.time())


@dataclass(slots=True)
class ReplicationLag:
    """Replication lag snapshot."""

    bytes: int = 0
    events: int = 0
    last_update: float = 0.0

    @property
    def lag_seconds(self) -> float:
        """Approximate lag в seconds (since last update)."""
        if self.last_update == 0.0:
            return 0.0
        return max(0.0, time.time() - self.last_update)


@dataclass(slots=True)
class PublicationSlot:
    """Replicated publication slot."""

    name: str
    table: str = ""
    plugin: str = "test_decoding"  # postgres logical decoding plugin.
    status: SlotStatus = SlotStatus.ACTIVE
    lag: ReplicationLag = field(default_factory=ReplicationLag)
    offset: Offset = field(default_factory=Offset)
    created_at: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


class CDCControlPlane:
    """High-level orchestrator для CDC replication slots.

    Pure-Python simulator. Wraps PublicationSlot registry + operations.
    """

    def __init__(self) -> None:
        self._slots: dict[str, PublicationSlot] = {}

    # ─── Slot lifecycle ──────────────────────────────────

    def create_slot(
        self, name: str, *, table: str = "", plugin: str = "test_decoding"
    ) -> PublicationSlot:
        """Create a new publication slot."""
        if name in self._slots:
            raise ValueError(f"Slot '{name}' already exists")
        slot = PublicationSlot(
            name=name,
            table=table,
            plugin=plugin,
            status=SlotStatus.ACTIVE,
            created_at=time.time(),
        )
        self._slots[name] = slot
        logger.info("CDC: created slot name=%s table=%s", name, table)
        return slot

    def drop_slot(self, name: str) -> bool:
        """Drop a publication slot. Returns True if existed."""
        slot = self._slots.get(name)
        if slot is None:
            return False
        slot.status = SlotStatus.DROPPED
        del self._slots[name]
        logger.info("CDC: dropped slot name=%s", name)
        return True

    def list_slots(self, *, status: SlotStatus | None = None) -> list[PublicationSlot]:
        """List slots, optionally filtered by status."""
        slots = list(self._slots.values())
        if status is not None:
            slots = [s for s in slots if s.status == status]
        return slots

    def get_slot(self, name: str) -> PublicationSlot | None:
        """Lookup a slot by name."""
        return self._slots.get(name)

    def slot_count(self) -> int:
        """Количество активных replication slot'ов."""
        return len(self._slots)

    # ─── State management ──────────────────────────────────

    def pause(self, name: str) -> bool:
        """Pause a slot."""
        slot = self._slots.get(name)
        if slot is None or slot.status != SlotStatus.ACTIVE:
            return False
        slot.status = SlotStatus.PAUSED
        logger.info("CDC: paused slot name=%s", name)
        return True

    def resume(self, name: str) -> bool:
        """Resume a paused slot."""
        slot = self._slots.get(name)
        if slot is None or slot.status != SlotStatus.PAUSED:
            return False
        slot.status = SlotStatus.ACTIVE
        logger.info("CDC: resumed slot name=%s", name)
        return True

    def fail(self, name: str, reason: str = "") -> bool:
        """Mark a slot as failed."""
        slot = self._slots.get(name)
        if slot is None:
            return False
        slot.status = SlotStatus.FAILED
        slot.metadata["failure_reason"] = reason
        return True

    # ─── Lag tracking ─────────────────────────────────────

    def update_lag(
        self, name: str, *, bytes: int = 0, events: int = 0
    ) -> ReplicationLag:
        """Update lag snapshot for a slot."""
        slot = self._slots.get(name)
        if slot is None:
            raise KeyError(f"Slot '{name}' not found")
        slot.lag = ReplicationLag(bytes=bytes, events=events, last_update=time.time())
        return slot.lag

    def get_lag(self, name: str) -> ReplicationLag | None:
        """Get current lag for a slot."""
        slot = self._slots.get(name)
        if slot is None:
            return None
        return slot.lag

    # ─── Offset / replay ─────────────────────────────────

    def update_offset(
        self, name: str, *, value: int, event_id: str | None = None
    ) -> Offset:
        """Update current offset для slot."""
        slot = self._slots.get(name)
        if slot is None:
            raise KeyError(f"Slot '{name}' not found")
        slot.offset = Offset(value=value, event_id=event_id, timestamp=time.time())
        return slot.offset

    def get_offset(self, name: str) -> Offset | None:
        """Получить offset по имени slot'а; ``None`` если нет."""
        slot = self._slots.get(name)
        if slot is None:
            return None
        return slot.offset

    def replay_from(
        self, name: str, *, offset: int | None = None, to_offset: int | None = None
    ) -> Offset:
        """Replay slot from a specific offset (or current).

        Args:
            name: Slot name.
            offset: Start offset (None = current).
            to_offset: Target offset (None = reset to start, i.e. offset).

        Returns:
            New offset after replay.
        """
        slot = self._slots.get(name)
        if slot is None:
            raise KeyError(f"Slot '{name}' not found")
        start = offset if offset is not None else slot.offset.value
        target = to_offset if to_offset is not None else start
        # In real PG: would call pg_replication_slot_advance().
        new_offset = Offset(value=target, event_id=None, timestamp=time.time())
        slot.offset = new_offset
        # Reset lag to 0.
        slot.lag = ReplicationLag()
        logger.info("CDC: replay slot name=%s from %s to %s", name, start, target)
        return new_offset

    # ─── Status / dashboard data ─────────────────────────

    def get_status(self, name: str) -> dict[str, Any] | None:
        """Get full status snapshot для UI dashboard."""
        slot = self._slots.get(name)
        if slot is None:
            return None
        return {
            "name": slot.name,
            "table": slot.table,
            "plugin": slot.plugin,
            "status": slot.status.value,
            "lag": {
                "bytes": slot.lag.bytes,
                "events": slot.lag.events,
                "lag_seconds": slot.lag.lag_seconds,
            },
            "offset": {"value": slot.offset.value, "event_id": slot.offset.event_id},
            "created_at": slot.created_at,
            "metadata": dict(slot.metadata),
        }

    def list_statuses(self) -> list[dict[str, Any]]:
        """List statuses for all slots (dashboard bulk view)."""
        return [s for s in (self.get_status(name) for name in self._slots) if s]

    # ─── Test helpers ────────────────────────────────────

    def simulate_lag_growth(
        self,
        name: str,
        *,
        bytes_per_sec: int = 1024,
        events_per_sec: int = 5,
        duration_seconds: float = 5.0,
    ) -> None:
        """Simulate lag growth (для testing dashboard).

        Calls update_lag multiple times для имитации накопления лага.
        """
        import time as _time

        end_at = _time.time() + duration_seconds
        cur_bytes = self.get_lag(name).bytes if self.get_lag(name) else 0
        cur_events = self.get_lag(name).events if self.get_lag(name) else 0
        while _time.time() < end_at:
            cur_bytes += bytes_per_sec
            cur_events += events_per_sec
            self.update_lag(name, bytes=cur_bytes, events=cur_events)
            _time.sleep(min(0.5, duration_seconds / 10))

    def clear(self) -> None:
        """Remove all slots (test helper)."""
        self._slots.clear()


# Singleton.
_plane: CDCControlPlane | None = None


def get_cdc_control_plane() -> CDCControlPlane:
    """Singleton-доступ к общей ``CDCControlPlane``."""
    global _plane
    if _plane is None:
        _plane = CDCControlPlane()
    return _plane


def reset_cdc_control_plane() -> None:
    """Сбросить singleton (следующий ``get_`` создаст новый)."""
    global _plane
    _plane = None
