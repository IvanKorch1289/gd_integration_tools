"""Focused tests for ``core.cdc_control_plane`` (Wave 4 #34)."""

from __future__ import annotations

import time

import pytest

from src.backend.core.cdc_control_plane import (
    CDCControlPlane,
    CDCSlotStatus,
    Offset,
    PublicationSlot,
    ReplicationLag,
    SlotStatus,
    get_cdc_control_plane,
)
from src.backend.core.cdc_control_plane.plane import reset_cdc_control_plane


@pytest.fixture(autouse=True)
def _reset() -> None:
    reset_cdc_control_plane()


class TestSlotStatus:
    def test_values(self) -> None:
        assert SlotStatus.ACTIVE.value == "active"
        assert SlotStatus.PAUSED.value == "paused"
        assert SlotStatus.FAILED.value == "failed"
        assert SlotStatus.DROPPED.value == "dropped"


class TestCDCSlotStatus:
    def test_values(self) -> None:
        """CDCSlotStatus has the same values as SlotStatus."""
        assert CDCSlotStatus.ACTIVE.value == "active"
        assert CDCSlotStatus.PAUSED.value == "paused"
        assert CDCSlotStatus.DROPPED.value == "dropped"


class TestOffset:
    def test_defaults(self) -> None:
        o = Offset()
        assert o.value == 0
        assert o.event_id is None
        assert o.timestamp == 0.0

    def test_now(self) -> None:
        before = time.time()
        o = Offset.now(value=100)
        assert o.value == 100
        assert o.timestamp >= before


class TestReplicationLag:
    def test_defaults(self) -> None:
        lag = ReplicationLag()
        assert lag.bytes == 0
        assert lag.events == 0
        assert lag.lag_seconds == 0.0

    def test_lag_seconds(self) -> None:
        lag = ReplicationLag(bytes=1024, events=5, last_update=time.time() - 2.0)
        assert 1.5 < lag.lag_seconds < 3.0


class TestPublicationSlot:
    def test_defaults(self) -> None:
        s = PublicationSlot(name="x")
        assert s.status == SlotStatus.ACTIVE
        assert s.plugin == "test_decoding"
        assert s.lag is not None
        assert s.offset is not None


class TestCDCControlPlaneInit:
    def test_init(self) -> None:
        p = CDCControlPlane()
        assert p.slot_count() == 0


class TestCreateSlot:
    def test_basic(self) -> None:
        p = CDCControlPlane()
        slot = p.create_slot("orders_pub", table="orders")
        assert slot.name == "orders_pub"
        assert slot.table == "orders"
        assert slot.status == SlotStatus.ACTIVE
        assert p.slot_count() == 1

    def test_default_plugin(self) -> None:
        p = CDCControlPlane()
        slot = p.create_slot("x")
        assert slot.plugin == "test_decoding"

    def test_duplicate_raises(self) -> None:
        p = CDCControlPlane()
        p.create_slot("x")
        with pytest.raises(ValueError, match="already exists"):
            p.create_slot("x")


class TestDropSlot:
    def test_drop_existing(self) -> None:
        p = CDCControlPlane()
        p.create_slot("x")
        assert p.drop_slot("x") is True
        assert p.slot_count() == 0

    def test_drop_missing(self) -> None:
        p = CDCControlPlane()
        assert p.drop_slot("missing") is False


class TestListSlots:
    def test_list_all(self) -> None:
        p = CDCControlPlane()
        p.create_slot("a")
        p.create_slot("b")
        p.create_slot("c")
        assert len(p.list_slots()) == 3

    def test_list_filtered_by_status(self) -> None:
        p = CDCControlPlane()
        p.create_slot("a")
        p.create_slot("b")
        p.pause("a")
        active = p.list_slots(status=SlotStatus.ACTIVE)
        paused = p.list_slots(status=SlotStatus.PAUSED)
        assert len(active) == 1
        assert len(paused) == 1


class TestGetSlot:
    def test_get_existing(self) -> None:
        p = CDCControlPlane()
        p.create_slot("x")
        assert p.get_slot("x") is not None

    def test_get_missing(self) -> None:
        p = CDCControlPlane()
        assert p.get_slot("missing") is None


class TestPauseResume:
    def test_pause(self) -> None:
        p = CDCControlPlane()
        p.create_slot("x")
        assert p.pause("x") is True
        assert p.get_slot("x").status == SlotStatus.PAUSED

    def test_pause_missing(self) -> None:
        p = CDCControlPlane()
        assert p.pause("missing") is False

    def test_pause_already_paused(self) -> None:
        p = CDCControlPlane()
        p.create_slot("x")
        p.pause("x")
        assert p.pause("x") is False

    def test_resume(self) -> None:
        p = CDCControlPlane()
        p.create_slot("x")
        p.pause("x")
        assert p.resume("x") is True
        assert p.get_slot("x").status == SlotStatus.ACTIVE

    def test_resume_active(self) -> None:
        p = CDCControlPlane()
        p.create_slot("x")
        assert p.resume("x") is False


class TestFail:
    def test_fail(self) -> None:
        p = CDCControlPlane()
        p.create_slot("x")
        assert p.fail("x", reason="connection lost") is True
        slot = p.get_slot("x")
        assert slot.status == SlotStatus.FAILED
        assert slot.metadata["failure_reason"] == "connection lost"

    def test_fail_missing(self) -> None:
        p = CDCControlPlane()
        assert p.fail("missing") is False


class TestUpdateLag:
    def test_basic(self) -> None:
        p = CDCControlPlane()
        p.create_slot("x")
        lag = p.update_lag("x", bytes=1024, events=5)
        assert lag.bytes == 1024
        assert lag.events == 5

    def test_update_missing(self) -> None:
        p = CDCControlPlane()
        with pytest.raises(KeyError, match="not found"):
            p.update_lag("missing", bytes=100)

    def test_get_lag(self) -> None:
        p = CDCControlPlane()
        p.create_slot("x")
        p.update_lag("x", bytes=2048)
        lag = p.get_lag("x")
        assert lag.bytes == 2048


class TestUpdateOffset:
    def test_basic(self) -> None:
        p = CDCControlPlane()
        p.create_slot("x")
        offset = p.update_offset("x", value=12345, event_id="tx-001")
        assert offset.value == 12345
        assert offset.event_id == "tx-001"

    def test_get_offset(self) -> None:
        p = CDCControlPlane()
        p.create_slot("x")
        p.update_offset("x", value=999)
        assert p.get_offset("x").value == 999

    def test_update_missing(self) -> None:
        p = CDCControlPlane()
        with pytest.raises(KeyError, match="not found"):
            p.update_offset("missing", value=1)


class TestReplay:
    def test_replay_from_offset(self) -> None:
        p = CDCControlPlane()
        p.create_slot("x")
        p.update_offset("x", value=1000)
        new_offset = p.replay_from("x", offset=500, to_offset=2000)
        assert new_offset.value == 2000

    def test_replay_keeps_current(self) -> None:
        """Replay без offset/to_offset → keep current."""
        p = CDCControlPlane()
        p.create_slot("x")
        p.update_offset("x", value=1000)
        new_offset = p.replay_from("x")
        assert new_offset.value == 1000

    def test_replay_resets_lag(self) -> None:
        p = CDCControlPlane()
        p.create_slot("x")
        p.update_lag("x", bytes=999)
        p.replay_from("x")
        assert p.get_lag("x").bytes == 0

    def test_replay_missing(self) -> None:
        p = CDCControlPlane()
        with pytest.raises(KeyError, match="not found"):
            p.replay_from("missing")


class TestGetStatus:
    def test_full_status(self) -> None:
        p = CDCControlPlane()
        p.create_slot("orders_pub", table="orders")
        p.update_offset("orders_pub", value=12345, event_id="tx-1")
        p.update_lag("orders_pub", bytes=1024, events=10)
        status = p.get_status("orders_pub")
        assert status["name"] == "orders_pub"
        assert status["table"] == "orders"
        assert status["status"] == "active"
        assert status["offset"]["value"] == 12345
        assert status["offset"]["event_id"] == "tx-1"
        assert status["lag"]["bytes"] == 1024

    def test_status_missing(self) -> None:
        p = CDCControlPlane()
        assert p.get_status("missing") is None


class TestListStatuses:
    def test_bulk_view(self) -> None:
        p = CDCControlPlane()
        p.create_slot("a")
        p.create_slot("b")
        statuses = p.list_statuses()
        assert len(statuses) == 2
        names = [s["name"] for s in statuses]
        assert "a" in names
        assert "b" in names


class TestClear:
    def test_clear(self) -> None:
        p = CDCControlPlane()
        p.create_slot("a")
        p.create_slot("b")
        p.clear()
        assert p.slot_count() == 0


class TestSingleton:
    def test_singleton(self) -> None:
        p1 = get_cdc_control_plane()
        p2 = get_cdc_control_plane()
        assert p1 is p2

    def test_reset(self) -> None:
        p1 = get_cdc_control_plane()
        reset_cdc_control_plane()
        p2 = get_cdc_control_plane()
        assert p1 is not p2


class TestExports:
    def test_module_all(self) -> None:
        from src.backend.core import cdc_control_plane

        assert len(cdc_control_plane.__all__) == 7


class TestRealisticExample:
    """Realistic: payment CDC slots management."""

    def test_payment_cdc_lifecycle(self) -> None:
        plane = get_cdc_control_plane()
        # Bootstrap: create slots for orders + audit_log.
        plane.create_slot("orders_pub", table="orders")
        plane.create_slot("audit_pub", table="audit_log")
        assert plane.slot_count() == 2

        # Simulate lag growth.
        plane.update_lag("orders_pub", bytes=2048, events=10)
        assert plane.get_lag("orders_pub").bytes == 2048

        # Offset tracking.
        plane.update_offset("orders_pub", value=12345, event_id="tx-100")
        assert plane.get_offset("orders_pub").value == 12345

        # Pause for maintenance.
        assert plane.pause("orders_pub") is True
        assert len(plane.list_slots(status=SlotStatus.PAUSED)) == 1

        # Resume + replay from earlier offset (e.g., after data fix).
        plane.resume("orders_pub")
        new_offset = plane.replay_from(
            "orders_pub", offset=10000, to_offset=12000
        )
        assert new_offset.value == 12000

        # Dashboard view.
        statuses = plane.list_statuses()
        assert len(statuses) == 2
        orders_status = next(
            s for s in statuses if s["name"] == "orders_pub"
        )
        assert orders_status["status"] == "active"
        assert orders_status["lag"]["bytes"] == 0  # replay reset lag.

        # Cleanup.
        assert plane.drop_slot("orders_pub") is True
        assert plane.drop_slot("audit_pub") is True
        assert plane.slot_count() == 0

    def test_unused_slot_no_status(self) -> None:
        """Slots без operations have empty status fields."""
        plane = CDCControlPlane()
        plane.create_slot("x")
        status = plane.get_status("x")
        assert status["offset"]["value"] == 0
        assert status["lag"]["bytes"] == 0
