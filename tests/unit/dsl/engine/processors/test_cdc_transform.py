"""Unit-тесты TransformCdcEventProcessor — S128 W2 (TD-023)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from src.backend.dsl.engine.processors.cdc_transform import (
    TransformCdcEventProcessor,
    _normalize_operation,
    _normalize_timestamp,
)

# --------------------------------------------------------------------------- #
# Stubs (matching pattern from test_cdc_capture.py)
# --------------------------------------------------------------------------- #


class _Message:
    def __init__(self, body: Any = None) -> None:
        self.body = body
        self.headers: dict[str, Any] = {}


class _Exchange:
    def __init__(self, properties: dict[str, Any] | None = None) -> None:
        self.properties = properties or {}
        self.in_message = _Message()
        self.out_message: _Message | None = None

    def set_property(self, key: str, value: Any) -> None:
        self.properties[key] = value

    def set_out(self, body: Any = None, headers: dict[str, Any] | None = None) -> None:
        self.out_message = _Message(body=body)
        if headers:
            self.out_message.headers = headers


class _Context:
    """Stub ExecutionContext."""


# --------------------------------------------------------------------------- #
# _normalize_operation
# --------------------------------------------------------------------------- #


class TestNormalizeOperation:
    def test_uppercase_passes_through(self) -> None:
        assert _normalize_operation("INSERT") == "INSERT"
        assert _normalize_operation("DELETE") == "DELETE"

    def test_lowercase_normalizes(self) -> None:
        assert _normalize_operation("insert") == "INSERT"
        assert _normalize_operation("update") == "UPDATE"

    def test_short_alias(self) -> None:
        assert _normalize_operation("I") == "INSERT"
        assert _normalize_operation("u") == "UPDATE"
        assert _normalize_operation("D") == "DELETE"

    def test_unknown_uppercases(self) -> None:
        assert _normalize_operation("custom") == "CUSTOM"
        assert _normalize_operation("FOO") == "FOO"

    def test_empty_returns_unknown(self) -> None:
        assert _normalize_operation("") == "UNKNOWN"


# --------------------------------------------------------------------------- #
# _normalize_timestamp
# --------------------------------------------------------------------------- #


class TestNormalizeTimestamp:
    def test_datetime_passthrough(self) -> None:
        dt = datetime(2026, 4, 19, 12, 0, 0, tzinfo=UTC)
        assert _normalize_timestamp(dt) == dt.isoformat()

    def test_string_passthrough(self) -> None:
        assert _normalize_timestamp("2026-04-19T12:00:00") == "2026-04-19T12:00:00"

    def test_none_returns_empty(self) -> None:
        assert _normalize_timestamp(None) == ""

    def test_other_stringified(self) -> None:
        assert _normalize_timestamp(12345) == "12345"


# --------------------------------------------------------------------------- #
# TransformCdcEventProcessor init validation
# --------------------------------------------------------------------------- #


class TestProcessorInit:
    def test_default_construction(self) -> None:
        proc = TransformCdcEventProcessor()
        assert proc.name == "cdc_transform"
        assert proc._operations_filter is None
        assert proc._project is None
        assert proc._include_old is True
        assert proc._include_new is True
        assert proc._drop_unknown is True

    def test_custom_construction(self) -> None:
        proc = TransformCdcEventProcessor(
            operations=["INSERT", "update"],
            project=["id", "table"],
            include_old=False,
            include_new=True,
            drop_unknown=False,
        )
        assert proc._operations_filter == {"INSERT", "UPDATE"}
        assert proc._project == ["id", "table"]
        assert proc._include_old is False
        assert proc._include_new is True
        assert proc._drop_unknown is False

    def test_custom_name(self) -> None:
        proc = TransformCdcEventProcessor(name="my_transform")
        assert proc.name == "my_transform"


# --------------------------------------------------------------------------- #
# TransformCdcEventProcessor.process
# --------------------------------------------------------------------------- #


class TestTransformCdcEventProcess:
    @pytest.mark.asyncio
    async def test_full_mode_no_filter(self) -> None:
        proc = TransformCdcEventProcessor()
        exchange = _Exchange()
        exchange.in_message.body = [
            {
                "operation": "INSERT",
                "table": "orders",
                "timestamp": "2026-04-19T12:00:00",
                "new": {"id": 1, "amount": 100},
            },
            {
                "operation": "DELETE",
                "table": "orders",
                "timestamp": "2026-04-19T13:00:00",
                "old": {"id": 2},
            },
        ]
        await proc.process(exchange, _Context())
        out = exchange.in_message.body
        assert len(out) == 2
        assert out[0]["operation"] == "INSERT"
        assert out[0]["table"] == "orders"
        assert out[0]["new"] == {"id": 1, "amount": 100}
        assert "old" not in out[0]
        assert out[1]["old"] == {"id": 2}
        assert "new" not in out[1]

    @pytest.mark.asyncio
    async def test_filter_operations(self) -> None:
        proc = TransformCdcEventProcessor(operations=["INSERT"])
        exchange = _Exchange()
        exchange.in_message.body = [
            {"operation": "INSERT", "table": "orders", "new": {"id": 1}},
            {"operation": "DELETE", "table": "orders", "old": {"id": 1}},
        ]
        await proc.process(exchange, _Context())
        out = exchange.in_message.body
        assert len(out) == 1
        assert out[0]["operation"] == "INSERT"

    @pytest.mark.asyncio
    async def test_filter_lowercase_operations(self) -> None:
        """operations принимает lowercase → нормализуется в UPPERCASE."""
        proc = TransformCdcEventProcessor(operations=["insert", "Update"])
        exchange = _Exchange()
        exchange.in_message.body = [
            {"operation": "INSERT", "table": "a", "new": {}},
            {"operation": "UPDATE", "table": "a", "old": {}, "new": {}},
            {"operation": "DELETE", "table": "a", "old": {}},
        ]
        await proc.process(exchange, _Context())
        assert len(exchange.in_message.body) == 2

    @pytest.mark.asyncio
    async def test_project(self) -> None:
        proc = TransformCdcEventProcessor(project=["id", "table", "operation"])
        exchange = _Exchange()
        exchange.in_message.body = [
            {
                "operation": "INSERT",
                "table": "orders",
                "timestamp": "2026-04-19T12:00:00",
                "new": {"id": 1, "amount": 100},
                "extra_field": "noise",
            }
        ]
        await proc.process(exchange, _Context())
        out = exchange.in_message.body
        assert len(out) == 1
        assert out[0] == {"operation": "INSERT", "table": "orders", "id": 1}

    @pytest.mark.asyncio
    async def test_project_with_timestamp_alias(self) -> None:
        """Поле 'ts' в project → берёт timestamp_field."""
        proc = TransformCdcEventProcessor(project=["table", "ts"], timestamp_field="ts")
        exchange = _Exchange()
        exchange.in_message.body = [
            {
                "operation": "INSERT",
                "table": "orders",
                "ts": "2026-04-19T12:00:00",
                "new": {"id": 1},
            }
        ]
        await proc.process(exchange, _Context())
        out = exchange.in_message.body
        assert out[0]["ts"] == "2026-04-19T12:00:00"
        assert "operation" not in out[0]

    @pytest.mark.asyncio
    async def test_drop_unknown(self) -> None:
        proc = TransformCdcEventProcessor(drop_unknown=True)
        exchange = _Exchange()
        exchange.in_message.body = [
            {"operation": "INSERT", "table": "orders", "new": {}},
            {"operation": "", "table": "orders", "new": {}},  # unknown
            {"operation": "INSERT", "table": "", "new": {}},  # unknown
        ]
        await proc.process(exchange, _Context())
        assert len(exchange.in_message.body) == 1

    @pytest.mark.asyncio
    async def test_keep_unknown_when_disabled(self) -> None:
        proc = TransformCdcEventProcessor(drop_unknown=False)
        exchange = _Exchange()
        exchange.in_message.body = [{"operation": "", "table": "orders", "new": {}}]
        await proc.process(exchange, _Context())
        assert len(exchange.in_message.body) == 1
        assert exchange.in_message.body[0]["operation"] == "UNKNOWN"

    @pytest.mark.asyncio
    async def test_source_alias_for_table(self) -> None:
        """CDC events may use 'source' instead of 'table'."""
        proc = TransformCdcEventProcessor()
        exchange = _Exchange()
        exchange.in_message.body = [
            {"operation": "INSERT", "source": "kafka_topic_a", "new": {}}
        ]
        await proc.process(exchange, _Context())
        assert exchange.in_message.body[0]["table"] == "kafka_topic_a"

    @pytest.mark.asyncio
    async def test_include_old_false(self) -> None:
        proc = TransformCdcEventProcessor(include_old=False)
        exchange = _Exchange()
        exchange.in_message.body = [
            {
                "operation": "UPDATE",
                "table": "orders",
                "old": {"id": 1, "amount": 50},
                "new": {"id": 1, "amount": 100},
            }
        ]
        await proc.process(exchange, _Context())
        out = exchange.in_message.body
        assert "old" not in out[0]
        assert out[0]["new"] == {"id": 1, "amount": 100}

    @pytest.mark.asyncio
    async def test_single_event_not_list(self) -> None:
        """Если body — одиночный dict (не list), обработать как list из 1."""
        proc = TransformCdcEventProcessor()
        exchange = _Exchange()
        exchange.in_message.body = {
            "operation": "INSERT",
            "table": "x",
            "new": {"id": 1},
        }
        await proc.process(exchange, _Context())
        assert len(exchange.in_message.body) == 1

    @pytest.mark.asyncio
    async def test_none_body_returns_immediately(self) -> None:
        proc = TransformCdcEventProcessor()
        exchange = _Exchange()
        exchange.in_message.body = None
        await proc.process(exchange, _Context())
        assert exchange.in_message.body is None

    @pytest.mark.asyncio
    async def test_non_dict_event_skipped(self) -> None:
        proc = TransformCdcEventProcessor()
        exchange = _Exchange()
        exchange.in_message.body = [
            "string_event",
            {"operation": "INSERT", "table": "x", "new": {}},
        ]
        await proc.process(exchange, _Context())
        assert len(exchange.in_message.body) == 1

    @pytest.mark.asyncio
    async def test_timestamp_datetime_object(self) -> None:
        """datetime объект в timestamp → isoformat."""
        proc = TransformCdcEventProcessor()
        exchange = _Exchange()
        dt = datetime(2026, 4, 19, 12, 0, 0, tzinfo=UTC)
        exchange.in_message.body = [
            {"operation": "INSERT", "table": "x", "timestamp": dt, "new": {}}
        ]
        await proc.process(exchange, _Context())
        assert exchange.in_message.body[0]["timestamp"] == dt.isoformat()


# --------------------------------------------------------------------------- #
# to_spec
# --------------------------------------------------------------------------- #


class TestToSpec:
    def test_spec_with_filter_and_project(self) -> None:
        proc = TransformCdcEventProcessor(
            operations=["INSERT"], project=["id", "table"]
        )
        spec = proc.to_spec()
        assert "cdc_transform" in spec
        assert spec["cdc_transform"]["operations"] == ["INSERT"]
        assert spec["cdc_transform"]["project"] == ["id", "table"]

    def test_spec_drops_none(self) -> None:
        proc = TransformCdcEventProcessor()
        spec = proc.to_spec()
        # None values должны быть отфильтрованы
        assert "operations" not in spec["cdc_transform"]
        assert "project" not in spec["cdc_transform"]
        # Дефолты всё ещё присутствуют
        assert spec["cdc_transform"]["include_old"] is True
        assert spec["cdc_transform"]["drop_unknown"] is True
