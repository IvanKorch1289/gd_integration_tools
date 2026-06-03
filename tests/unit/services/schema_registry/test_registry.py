"""Unit tests for src.backend.services.schema_registry.registry."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.backend.services.schema_registry.registry import (
    SchemaEntry,
    SchemaKind,
    ServiceSchemaRegistry,
    get_schema_registry,
)


class TestSchemaEntry:
    def test_defaults(self) -> None:
        entry = SchemaEntry(kind=SchemaKind.ROUTE, name="test")
        assert entry.spec_schema is None
        assert entry.output_schema is None
        assert entry.meta == {}


class TestServiceSchemaRegistry:
    def test_register_and_get(self) -> None:
        reg = ServiceSchemaRegistry()
        entry = SchemaEntry(kind=SchemaKind.ROUTE, name="r1", spec_schema={"type": "object"})
        reg.register(entry)
        assert reg.get(SchemaKind.ROUTE, "r1") is entry

    def test_register_overwrite(self) -> None:
        reg = ServiceSchemaRegistry()
        e1 = SchemaEntry(kind=SchemaKind.ROUTE, name="r1", spec_schema={"a": 1})
        e2 = SchemaEntry(kind=SchemaKind.ROUTE, name="r1", spec_schema={"a": 2})
        reg.register(e1)
        reg.register(e2)
        assert reg.get(SchemaKind.ROUTE, "r1") is e2

    def test_get_missing(self) -> None:
        reg = ServiceSchemaRegistry()
        assert reg.get(SchemaKind.ROUTE, "missing") is None

    def test_list_kind_sorted(self) -> None:
        reg = ServiceSchemaRegistry()
        e1 = SchemaEntry(kind=SchemaKind.ROUTE, name="b")
        e2 = SchemaEntry(kind=SchemaKind.ROUTE, name="a")
        reg.register(e1)
        reg.register(e2)
        assert reg.list_kind(SchemaKind.ROUTE) == [e2, e1]

    def test_list_kind_empty(self) -> None:
        reg = ServiceSchemaRegistry()
        assert reg.list_kind(SchemaKind.WORKFLOW) == []

    def test_summary(self) -> None:
        reg = ServiceSchemaRegistry()
        reg.register(SchemaEntry(kind=SchemaKind.ROUTE, name="r1"))
        reg.register(SchemaEntry(kind=SchemaKind.ACTION, name="a1"))
        summary = reg.summary()
        assert summary["route"] == 1
        assert summary["action"] == 1
        assert summary["workflow"] == 0

    def test_clear_all(self) -> None:
        reg = ServiceSchemaRegistry()
        reg.register(SchemaEntry(kind=SchemaKind.ROUTE, name="r1"))
        reg.clear()
        assert reg.get(SchemaKind.ROUTE, "r1") is None
        assert reg.summary()["route"] == 0

    def test_clear_by_kind(self) -> None:
        reg = ServiceSchemaRegistry()
        reg.register(SchemaEntry(kind=SchemaKind.ROUTE, name="r1"))
        reg.register(SchemaEntry(kind=SchemaKind.ACTION, name="a1"))
        reg.clear(kind=SchemaKind.ROUTE)
        assert reg.get(SchemaKind.ROUTE, "r1") is None
        assert reg.get(SchemaKind.ACTION, "a1") is not None

    def test_to_snapshot(self) -> None:
        reg = ServiceSchemaRegistry()
        reg.register(
            SchemaEntry(
                kind=SchemaKind.ROUTE, name="r1", spec_schema={"type": "object"}, meta={"v": 1}
            )
        )
        snap = reg.to_snapshot()
        assert snap["version"] == "2.0"
        assert len(snap["entries"]) == 1
        assert snap["entries"][0]["kind"] == "route"
        assert snap["entries"][0]["name"] == "r1"

    def test_from_snapshot(self) -> None:
        reg = ServiceSchemaRegistry()
        reg.from_snapshot(
            {
                "version": "2.0",
                "entries": [
                    {
                        "kind": "workflow",
                        "name": "w1",
                        "spec_schema": {"type": "object"},
                        "output_schema": None,
                        "meta": {},
                    }
                ],
            }
        )
        entry = reg.get(SchemaKind.WORKFLOW, "w1")
        assert entry is not None
        assert entry.name == "w1"

    def test_from_snapshot_bad_version(self) -> None:
        reg = ServiceSchemaRegistry()
        with pytest.raises(ValueError, match="Unsupported snapshot version"):
            reg.from_snapshot({"version": "1.0"})

    def test_strict_validation_valid(self) -> None:
        pytest.importorskip("jsonschema")
        reg = ServiceSchemaRegistry(strict_validation=True)
        entry = SchemaEntry(
            kind=SchemaKind.ROUTE,
            name="r1",
            spec_schema={"type": "object"},
        )
        reg.register(entry)
        assert reg.get(SchemaKind.ROUTE, "r1") is entry

    def test_strict_validation_invalid(self) -> None:
        pytest.importorskip("jsonschema")
        reg = ServiceSchemaRegistry(strict_validation=True)
        entry = SchemaEntry(
            kind=SchemaKind.ROUTE,
            name="r1",
            spec_schema={"type": "invalid_type_xyz"},
        )
        with pytest.raises(ValueError, match="Invalid JSON-Schema"):
            reg.register(entry)

    def test_metrics_counter(self) -> None:
        metrics = MagicMock()
        counter = MagicMock()
        metrics.counter.return_value = counter
        counter.labels.return_value = counter
        reg = ServiceSchemaRegistry(metrics=metrics)
        reg.register(SchemaEntry(kind=SchemaKind.ROUTE, name="r1"))
        metrics.counter.assert_called()
        counter.inc.assert_called()


class TestGetSchemaRegistry:
    def test_singleton(self) -> None:
        r1 = get_schema_registry()
        r2 = get_schema_registry()
        assert r1 is r2
        assert isinstance(r1, ServiceSchemaRegistry)
