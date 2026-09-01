"""Unit-тесты ``core.cdc.source`` — coverage ratchet (S48 W39).

core/cdc/source.py — R2.1 CDC primitives: Pydantic models
(CDCCursor, CDCEvent, CDCOperation Literal) + CDCSource Protocol
(subscribe/ack/replay/close) + FakeCDCSource concrete impl.
164 LOC, 0% coverage (после S48 W23 facade coverage).

Цель slice: поднять coverage на Pydantic models + FakeCDCSource (concrete
impl с async generators для subscribe/replay).
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.backend.core.cdc.source import (
    CDCCursor,
    CDCEvent,
    CDCSource,
    FakeCDCSource,
)


@pytest.mark.unit
class TestCdcSourceModels:
    """Pydantic models: CDCCursor + CDCEvent."""

    def test_cdc_cursor_instantiation(self) -> None:
        """``CDCCursor`` — Pydantic BaseModel с value + backend + topic."""
        cursor = CDCCursor(value="opaque_123", backend="pg_logical")
        assert cursor.value == "opaque_123"
        assert cursor.backend == "pg_logical"
        assert cursor.topic is None  # optional

    def test_cdc_cursor_with_topic(self) -> None:
        """``CDCCursor`` с topic (S178 fix)."""
        cursor = CDCCursor(
            value="kafka_offset_42",
            backend="debezium",
            topic="public.users",
        )
        assert cursor.topic == "public.users"

    def test_cdc_cursor_is_frozen(self) -> None:
        """``CDCCursor`` — frozen model (model_config frozen=True)."""
        cursor = CDCCursor(value="x", backend="y")
        with pytest.raises((TypeError, ValueError, AttributeError)):
            cursor.value = "z"  # type: ignore[misc]

    def test_cdc_event_minimal(self) -> None:
        """``CDCEvent`` минимальный: только обязательные поля."""
        event = CDCEvent(
            operation="INSERT",
            source="pg_logical",
            table="public.users",
            timestamp=datetime.now(timezone.utc),
            cursor=CDCCursor(value="x", backend="y"),
        )
        assert event.operation == "INSERT"
        assert event.source == "pg_logical"
        assert event.table == "public.users"
        assert event.cursor.value == "x"

    def test_cdc_event_full(self) -> None:
        """``CDCEvent`` full: new + old + metadata."""
        event = CDCEvent(
            operation="UPDATE",
            source="pg_logical",
            table="orders",
            timestamp=datetime.now(timezone.utc),
            cursor=CDCCursor(value="x", backend="y"),
            new={"id": 42, "status": "shipped"},
            old={"id": 42, "status": "pending"},
            metadata={"tx_id": "tx-001"},
        )
        assert event.new == {"id": 42, "status": "shipped"}
        assert event.old == {"id": 42, "status": "pending"}
        assert event.metadata == {"tx_id": "tx-001"}


@pytest.mark.unit
class TestCdcSourceProtocol:
    """``CDCSource`` — runtime_checkable Protocol."""

    def test_cdc_source_is_protocol(self) -> None:
        """``CDCSource`` — runtime_checkable Protocol."""
        from typing import Protocol

        assert isinstance(CDCSource, type) and issubclass(CDCSource, Protocol)
        assert hasattr(CDCSource, "__subclasshook__")

    def test_fakecdcsource_implements_protocol(self) -> None:
        """``FakeCDCSource`` — concrete impl of CDCSource Protocol."""
        assert issubclass(FakeCDCSource, CDCSource)


def _make_event(table: str, cursor_value: str, op: str = "INSERT") -> CDCEvent:
    """Helper: CDCEvent минимальный."""
    return CDCEvent(
        operation=op,  # type: ignore[arg-type]
        source="test",
        table=table,
        timestamp=datetime.now(timezone.utc),
        cursor=CDCCursor(value=cursor_value, backend="test"),
    )


@pytest.mark.unit
class TestFakeCDCSource:
    """``FakeCDCSource`` — in-memory test stub (async generator)."""

    def test_initial_state_empty(self) -> None:
        """FakeCDCSource без events → empty state."""
        fake = FakeCDCSource(events=[])
        assert fake.closed is False
        assert fake.acked == []

    def test_with_events_initializes(self) -> None:
        """FakeCDCSource с events сохраняет в private _events."""
        events = [_make_event("a", "1"), _make_event("b", "2")]
        fake = FakeCDCSource(events=events)
        assert fake.closed is False
        assert fake.acked == []
        # _events — private attr, не проверяем (per encapsulation)

    @pytest.mark.asyncio
    async def test_subscribe_filters_by_tables(self) -> None:
        """subscribe(tables=['x']) → только события с table='x'."""
        events = [
            _make_event("x", "1"),
            _make_event("y", "2"),
            _make_event("x", "3"),
        ]
        fake = FakeCDCSource(events=events)
        result = []
        async for ev in fake.subscribe(tables=["x"]):
            result.append(ev)
        assert len(result) == 2
        assert result[0].cursor.value == "1"
        assert result[1].cursor.value == "3"

    @pytest.mark.asyncio
    async def test_subscribe_with_start_cursor_skips_prior(self) -> None:
        """subscribe(start_cursor=X) → пропускает события до X включительно."""
        events = [
            _make_event("x", "1"),
            _make_event("x", "2"),
            _make_event("x", "3"),
        ]
        fake = FakeCDCSource(events=events)
        start = CDCCursor(value="1", backend="test")
        result = []
        async for ev in fake.subscribe(tables=["x"], start_cursor=start):
            result.append(ev)
        # Start_cursor='1' → skip until cursor.value='1' (inclusive),
        # после — yield '2' и '3'.
        assert len(result) == 2
        assert result[0].cursor.value == "2"

    @pytest.mark.asyncio
    async def test_ack_appends_to_acked(self) -> None:
        """ack(cursor) → append в self.acked."""
        fake = FakeCDCSource(events=[])
        c1 = CDCCursor(value="c1", backend="y")
        c2 = CDCCursor(value="c2", backend="y")
        await fake.ack(c1)
        await fake.ack(c2)
        assert fake.acked == [c1, c2]

    @pytest.mark.asyncio
    async def test_close_sets_closed_flag(self) -> None:
        """close() → closed=True."""
        fake = FakeCDCSource(events=[])
        await fake.close()
        assert fake.closed is True

    @pytest.mark.asyncio
    async def test_replay_emits_events_in_range(self) -> None:
        """replay(start_cursor=X, end_cursor=Y) → events от X до Y inclusive."""
        events = [
            _make_event("x", "1"),
            _make_event("x", "2"),
            _make_event("x", "3"),
            _make_event("x", "4"),
        ]
        fake = FakeCDCSource(events=events)
        start = CDCCursor(value="1", backend="test")
        end = CDCCursor(value="3", backend="test")
        result = []
        async for ev in fake.replay(start_cursor=start, end_cursor=end):
            result.append(ev)
        # In_range starts when cursor.value=='1', yields all until end=='3'.
        # Then return (early exit).
        assert len(result) == 3
        assert [ev.cursor.value for ev in result] == ["1", "2", "3"]

    @pytest.mark.asyncio
    async def test_replay_without_end_cursor_yields_all(self) -> None:
        """replay(start_cursor=X) без end_cursor → yield все события от X."""
        events = [
            _make_event("x", "1"),
            _make_event("x", "2"),
            _make_event("x", "3"),
        ]
        fake = FakeCDCSource(events=events)
        start = CDCCursor(value="1", backend="test")
        result = []
        async for ev in fake.replay(start_cursor=start):
            result.append(ev)
        assert [ev.cursor.value for ev in result] == ["1", "2", "3"]
