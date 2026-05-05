# ruff: noqa: S101
"""Тесты `CDCSource` Protocol + `FakeCDCSource` + Debezium parser (R2.1)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from src.core.cdc import CDCCursor, CDCEvent, CDCSource, FakeCDCSource
from src.infrastructure.cdc.debezium_events_backend import parse_debezium_event


def _ev(
    table: str, op: str = "UPSERT", cursor_value: str = "1", payload: int = 0
) -> CDCEvent:
    return CDCEvent(
        operation=op,  # type: ignore[arg-type]
        source="fake",
        table=table,
        timestamp=datetime.now(timezone.utc),
        cursor=CDCCursor(value=cursor_value, backend="fake"),
        new={"id": payload},
    )


class TestCDCEvent:
    def test_construct_minimal(self) -> None:
        ev = _ev("orders")
        assert ev.operation == "UPSERT"
        assert ev.table == "orders"
        assert ev.cursor.value == "1"

    def test_invalid_operation_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CDCEvent(
                operation="BOGUS",  # type: ignore[arg-type]
                source="x",
                table="t",
                timestamp=datetime.now(timezone.utc),
                cursor=CDCCursor(value="1", backend="x"),
            )

    def test_frozen(self) -> None:
        ev = _ev("orders")
        with pytest.raises(ValidationError):
            ev.table = "other"  # type: ignore[misc]


class TestFakeCDCSourceIsProtocol:
    def test_runtime_checkable(self) -> None:
        source = FakeCDCSource(events=[])
        assert isinstance(source, CDCSource)


@pytest.mark.asyncio
class TestFakeCDCSourceBehavior:
    async def test_subscribe_filters_by_tables(self) -> None:
        events = [_ev("orders", cursor_value="1"), _ev("clients", cursor_value="2")]
        source = FakeCDCSource(events=events)
        seen = []
        async for ev in source.subscribe(tables=["orders"]):
            seen.append(ev)
        assert len(seen) == 1
        assert seen[0].table == "orders"

    async def test_ack_records_cursor(self) -> None:
        source = FakeCDCSource(events=[])
        cursor = CDCCursor(value="42", backend="fake")
        await source.ack(cursor)
        assert source.acked == [cursor]

    async def test_close_marks_source(self) -> None:
        source = FakeCDCSource(events=[])
        await source.close()
        assert source.closed is True

    async def test_subscribe_skips_until_start_cursor(self) -> None:
        events = [
            _ev("orders", cursor_value="1"),
            _ev("orders", cursor_value="2"),
            _ev("orders", cursor_value="3"),
        ]
        source = FakeCDCSource(events=events)
        seen = []
        async for ev in source.subscribe(
            tables=["orders"], start_cursor=CDCCursor(value="1", backend="fake")
        ):
            seen.append(ev)
        # Пропустили "1", получили "2" и "3".
        assert [e.cursor.value for e in seen] == ["2", "3"]

    async def test_replay_in_range(self) -> None:
        events = [
            _ev("orders", cursor_value="1"),
            _ev("orders", cursor_value="2"),
            _ev("orders", cursor_value="3"),
        ]
        source = FakeCDCSource(events=events)
        seen = []
        async for ev in source.replay(
            start_cursor=CDCCursor(value="2", backend="fake"),
            end_cursor=CDCCursor(value="3", backend="fake"),
        ):
            seen.append(ev)
        assert [e.cursor.value for e in seen] == ["2", "3"]


class TestParseDebeziumEvent:
    def test_create_event(self) -> None:
        raw = {
            "op": "c",
            "ts_ms": 1735689600000,
            "source": {"db": "main", "table": "orders", "snapshot": "false"},
            "before": None,
            "after": {"id": 1, "amount": 100},
        }
        ev = parse_debezium_event(raw, kafka_offset=42, kafka_partition=0)
        assert ev is not None
        assert ev.operation == "INSERT"
        assert ev.table == "orders"
        assert ev.new == {"id": 1, "amount": 100}
        assert ev.old is None
        assert ev.cursor.value == "0:42"
        assert ev.cursor.backend == "debezium"
        assert ev.metadata["db"] == "main"

    def test_delete_event(self) -> None:
        raw = {
            "op": "d",
            "source": {"db": "main", "table": "orders"},
            "before": {"id": 5},
            "after": None,
        }
        ev = parse_debezium_event(raw, kafka_offset=1, kafka_partition=2)
        assert ev is not None
        assert ev.operation == "DELETE"
        assert ev.old == {"id": 5}
        assert ev.new is None

    def test_unknown_op_returns_none(self) -> None:
        raw = {"op": "x", "source": {"table": "t"}}
        assert parse_debezium_event(raw, kafka_offset=0, kafka_partition=0) is None

    def test_missing_table_returns_none(self) -> None:
        raw = {"op": "c", "source": {}}
        assert parse_debezium_event(raw, kafka_offset=0, kafka_partition=0) is None


class TestInfrastructureBackendsAreProtocol:
    """Smoke: каждый infrastructure backend реализует CDCSource."""

    def test_poll_backend(self) -> None:
        from src.infrastructure.cdc import PollCDCBackend

        backend = PollCDCBackend(profile="default")
        assert isinstance(backend, CDCSource)

    def test_listen_notify_backend(self) -> None:
        from src.infrastructure.cdc import ListenNotifyCDCBackend

        backend = ListenNotifyCDCBackend(dsn="postgresql://localhost/db")
        assert isinstance(backend, CDCSource)

    def test_debezium_events_backend(self) -> None:
        from src.infrastructure.cdc import DebeziumEventsCDCBackend

        backend = DebeziumEventsCDCBackend(bootstrap_servers="localhost:9092")
        assert isinstance(backend, CDCSource)
