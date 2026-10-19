"""Tests for ``src.backend.dsl.engine.processors.event_store.types``.

S66 W1: core data types (EventStream StrEnum + Event dataclass).
"""

from __future__ import annotations

import time
import uuid

from src.backend.dsl.engine.processors.event_store.types import Event, EventStream


class TestEventStreamEnum:
    """EventStream StrEnum — имена event streams/topics/aggregates."""

    def test_all_members_exist(self) -> None:
        assert hasattr(EventStream, "ORDER")
        assert hasattr(EventStream, "PAYMENT")
        assert hasattr(EventStream, "INVENTORY")
        assert hasattr(EventStream, "USER")
        assert hasattr(EventStream, "AUDIT")
        assert hasattr(EventStream, "CUSTOM")

    def test_six_total_members(self) -> None:
        assert len(EventStream) == 6

    def test_string_values(self) -> None:
        assert EventStream.ORDER.value == "order"
        assert EventStream.PAYMENT.value == "payment"
        assert EventStream.INVENTORY.value == "inventory"
        assert EventStream.USER.value == "user"
        assert EventStream.AUDIT.value == "audit"
        assert EventStream.CUSTOM.value == "custom"

    def test_is_strenum(self) -> None:
        # StrEnum — str + Enum
        assert isinstance(EventStream.ORDER, str)
        assert EventStream.ORDER == "order"  # str comparison works


class TestEventDefaults:
    """Event dataclass defaults."""

    def test_minimal_construction(self) -> None:
        e = Event(aggregate_id="a1", event_type="order.placed")
        assert e.aggregate_id == "a1"
        assert e.event_type == "order.placed"

    def test_default_payload_empty_dict(self) -> None:
        e = Event(aggregate_id="a", event_type="x")
        assert e.payload == {}
        assert isinstance(e.payload, dict)

    def test_default_stream(self) -> None:
        e = Event(aggregate_id="a", event_type="x")
        assert e.stream == EventStream.CUSTOM

    def test_default_version(self) -> None:
        e = Event(aggregate_id="a", event_type="x")
        assert e.version == 1

    def test_default_event_id_is_uuid(self) -> None:
        e = Event(aggregate_id="a", event_type="x")
        # event_id — auto-generated UUID
        # Должен парситься как UUID
        uuid.UUID(e.event_id)  # не должно бросить

    def test_default_timestamp_is_recent(self) -> None:
        before = time.time()
        e = Event(aggregate_id="a", event_type="x")
        after = time.time()
        assert before <= e.timestamp <= after

    def test_default_metadata_empty_dict(self) -> None:
        e = Event(aggregate_id="a", event_type="x")
        assert e.metadata == {}
        assert isinstance(e.metadata, dict)


class TestEventExplicit:
    """Явные значения."""

    def test_explicit_payload(self) -> None:
        payload = {"amount": 100, "currency": "RUB"}
        e = Event(aggregate_id="a", event_type="x", payload=payload)
        assert e.payload == payload

    def test_explicit_stream_order(self) -> None:
        e = Event(aggregate_id="a", event_type="x", stream=EventStream.ORDER)
        assert e.stream == EventStream.ORDER

    def test_explicit_version(self) -> None:
        e = Event(aggregate_id="a", event_type="x", version=42)
        assert e.version == 42

    def test_explicit_event_id(self) -> None:
        explicit_id = "fixed-id-123"
        e = Event(aggregate_id="a", event_type="x", event_id=explicit_id)
        assert e.event_id == explicit_id

    def test_explicit_timestamp(self) -> None:
        ts = 1234567890.5
        e = Event(aggregate_id="a", event_type="x", timestamp=ts)
        assert e.timestamp == ts

    def test_explicit_metadata(self) -> None:
        md = {"user_id": "u1", "tenant_id": "t1"}
        e = Event(aggregate_id="a", event_type="x", metadata=md)
        assert e.metadata == md


class TestEventUniqueEventId:
    """Каждый Event получает уникальный event_id (default factory)."""

    def test_two_events_have_different_ids(self) -> None:
        e1 = Event(aggregate_id="a", event_type="x")
        e2 = Event(aggregate_id="a", event_type="x")
        assert e1.event_id != e2.event_id

    def test_event_ids_are_valid_uuids(self) -> None:
        for _ in range(5):
            e = Event(aggregate_id="a", event_type="x")
            # Парсится как UUID без ошибок
            parsed = uuid.UUID(e.event_id)
            assert str(parsed) == e.event_id


class TestEventToDict:
    """Event.to_dict() — сериализация для transport/storage."""

    def test_returns_dict(self) -> None:
        e = Event(aggregate_id="a1", event_type="order.placed")
        d = e.to_dict()
        assert isinstance(d, dict)

    def test_contains_all_fields(self) -> None:
        e = Event(aggregate_id="a1", event_type="order.placed")
        d = e.to_dict()
        expected_keys = {
            "event_id",
            "aggregate_id",
            "event_type",
            "stream",
            "payload",
            "version",
            "timestamp",
            "metadata",
        }
        assert set(d.keys()) == expected_keys

    def test_field_values_match(self) -> None:
        e = Event(
            aggregate_id="a1",
            event_type="order.placed",
            payload={"x": 1},
            version=5,
        )
        d = e.to_dict()
        assert d["aggregate_id"] == "a1"
        assert d["event_type"] == "order.placed"
        assert d["payload"] == {"x": 1}
        assert d["version"] == 5

    def test_stream_value_not_enum(self) -> None:
        e = Event(aggregate_id="a", event_type="x", stream=EventStream.ORDER)
        d = e.to_dict()
        # В dict — value (str), а не enum
        assert d["stream"] == "order"
        assert not isinstance(d["stream"], EventStream)

    def test_payload_dict_copied(self) -> None:
        original_payload = {"x": 1}
        e = Event(aggregate_id="a", event_type="x", payload=original_payload)
        d = e.to_dict()
        d["payload"]["y"] = 2
        # Original не изменился (dict copy)
        assert "y" not in original_payload

    def test_metadata_dict_copied(self) -> None:
        original_md = {"k": 1}
        e = Event(aggregate_id="a", event_type="x", metadata=original_md)
        d = e.to_dict()
        d["metadata"]["new"] = "v"
        assert "new" not in original_md


class TestEventEquality:
    """Event equality (dataclass)."""

    def test_equal_when_all_fields_match(self) -> None:
        e1 = Event(
            aggregate_id="a",
            event_type="x",
            event_id="fixed",
            timestamp=1.0,
        )
        e2 = Event(
            aggregate_id="a",
            event_type="x",
            event_id="fixed",
            timestamp=1.0,
        )
        assert e1 == e2

    def test_not_equal_when_different(self) -> None:
        e1 = Event(aggregate_id="a", event_type="x", event_id="id1")
        e2 = Event(aggregate_id="a", event_type="x", event_id="id2")
        assert e1 != e2


class TestEventRepr:
    """Event repr содержит class name."""

    def test_repr_contains_class_name(self) -> None:
        e = Event(aggregate_id="a", event_type="x")
        assert "Event" in repr(e)


class TestPayloadIndependence:
    """default_factory=dict — каждая instance имеет свой dict."""

    def test_payload_independent_per_instance(self) -> None:
        e1 = Event(aggregate_id="a", event_type="x")
        e2 = Event(aggregate_id="a", event_type="x")
        e1.payload["new"] = "value"
        assert e2.payload == {}

    def test_metadata_independent_per_instance(self) -> None:
        e1 = Event(aggregate_id="a", event_type="x")
        e2 = Event(aggregate_id="a", event_type="x")
        e1.metadata["new"] = "value"
        assert e2.metadata == {}