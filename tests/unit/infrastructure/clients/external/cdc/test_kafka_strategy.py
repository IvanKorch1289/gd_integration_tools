"""Tests for _KafkaDebeziumStrategy (S166 W1)."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.infrastructure.clients.external.cdc.events import (
    CDCEvent,
    CDCSubscription,
)
from src.backend.infrastructure.clients.external.cdc.kafka_strategy import (
    _KafkaDebeziumStrategy,
)


def _make_subscription(active: bool = True) -> CDCSubscription:
    return CDCSubscription(
        profile="oracle_prod",
        tables=["orders", "customers"],
        active=active,
    )


def test_parse_debezium_insert() -> None:
    """S166 W1: parse Debezium 'c' op → CDCEvent INSERT."""
    strategy = _KafkaDebeziumStrategy(bootstrap_servers="dummy:9092")
    payload = {
        "op": "c",
        "before": None,
        "after": {"id": 1, "name": "alice"},
        "ts_ms": 1700000000000,
    }
    event = strategy._parse_debezium_event(payload, table="orders", profile="prod")
    assert event is not None
    assert event.operation == "INSERT"
    assert event.table == "orders"
    assert event.new == {"id": 1, "name": "alice"}
    assert event.old is None


def test_parse_debezium_update() -> None:
    strategy = _KafkaDebeziumStrategy()
    payload = {
        "op": "u",
        "before": {"id": 1, "name": "alice"},
        "after": {"id": 1, "name": "bob"},
        "ts_ms": 1700000000000,
    }
    event = strategy._parse_debezium_event(payload, table="orders", profile="prod")
    assert event is not None
    assert event.operation == "UPDATE"
    assert event.old == {"id": 1, "name": "alice"}
    assert event.new == {"id": 1, "name": "bob"}


def test_parse_debezium_delete() -> None:
    strategy = _KafkaDebeziumStrategy()
    payload = {
        "op": "d",
        "before": {"id": 1},
        "after": None,
        "ts_ms": 1700000000000,
    }
    event = strategy._parse_debezium_event(payload, table="orders", profile="prod")
    assert event is not None
    assert event.operation == "DELETE"
    assert event.old == {"id": 1}
    assert event.new is None


def test_parse_debezium_unknown_op_returns_none() -> None:
    strategy = _KafkaDebeziumStrategy()
    payload = {"op": "x", "ts_ms": 1700000000000}
    event = strategy._parse_debezium_event(payload, table="orders", profile="prod")
    assert event is None


def test_parse_debezium_handles_missing_keys() -> None:
    """S166 W1: robust to partial payloads."""
    strategy = _KafkaDebeziumStrategy()
    payload = {"op": "c"}  # no before/after/ts_ms
    event = strategy._parse_debezium_event(payload, table="orders", profile="prod")
    assert event is not None
    assert event.operation == "INSERT"
    assert event.new is None
