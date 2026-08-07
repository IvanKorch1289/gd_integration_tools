"""Unit tests для :mod:`src.backend.services.schema_registry.typed_adapter`.

D-AUDIT-A5-01 fix (cycle 1) — проверяет typed wrapper для public API
boundary ``ServiceSchemaRegistry``: TypeAdapter validation, round-trip и
обработка ошибок.

Покрывает:
    * Round-trip :class:`SchemaEntryView` (entry → dict → entry).
    * Round-trip :class:`SnapshotView` (registry → snapshot → registry).
    * :class:`pydantic.TypeAdapter` validation на ``kind`` / ``name``.
    * Обработка невалидной версии snapshot.
    * Lazy ``schema_view`` property на ``ServiceSchemaRegistry``.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from src.backend.services.schema_registry import (
    CURRENT_SNAPSHOT_VERSION,
    SchemaEntry,
    SchemaEntryView,
    SchemaKind,
    SchemaTypedAdapter,
    ServiceSchemaRegistry,
    SnapshotView,
)

# ── SchemaEntryView — round-trip ────────────────────────────────────


def test_entry_view_round_trip_preserves_fields() -> None:
    """``to_json_dict`` → ``from_json_dict`` сохраняет все поля ``SchemaEntry``."""
    original = SchemaEntry(
        kind=SchemaKind.ROUTE,
        name="orders.create",
        spec_schema={"type": "object", "properties": {"id": {"type": "string"}}},
        output_schema={"type": "object"},
        meta={"protocol": "http", "tier": 1},
    )
    adapter = SchemaTypedAdapter()
    view = adapter.entry_view(original)
    payload = view.to_json_dict()

    assert payload["kind"] == "route"
    assert payload["name"] == "orders.create"
    assert payload["spec_schema"] == original.spec_schema
    assert payload["output_schema"] == original.output_schema
    assert payload["meta"] == {"protocol": "http", "tier": 1}

    restored_view = SchemaEntryView.from_json_dict(payload)
    assert restored_view.entry == original


def test_entry_view_from_dict_via_adapter() -> None:
    """``SchemaTypedAdapter.entry_from_dict`` строит :class:`SchemaEntry`."""
    adapter = SchemaTypedAdapter()
    payload: dict[str, Any] = {
        "kind": "processor",
        "name": "core:http_call",
        "spec_schema": {"type": "object"},
        "output_schema": None,
        "meta": {"namespace": "core"},
    }
    entry = adapter.entry_from_dict(payload)

    assert entry.kind == SchemaKind.PROCESSOR
    assert entry.name == "core:http_call"
    assert entry.spec_schema == {"type": "object"}
    assert entry.output_schema is None
    assert entry.meta == {"namespace": "core"}


# ── SnapshotView — round-trip ───────────────────────────────────────


def test_snapshot_view_round_trip_via_registry() -> None:
    """``registry.to_snapshot`` → ``SnapshotView.from_json_dict`` round-trip."""
    reg = ServiceSchemaRegistry()
    reg.register(
        SchemaEntry(
            kind=SchemaKind.ROUTE,
            name="orders.create",
            spec_schema={"type": "object"},
            meta={"protocol": "http"},
        )
    )
    reg.register(
        SchemaEntry(
            kind=SchemaKind.PROCESSOR,
            name="core:http_call",
            output_schema={"type": "string"},
        )
    )

    snapshot_payload = reg.to_snapshot()
    assert snapshot_payload["version"] == CURRENT_SNAPSHOT_VERSION

    view = SnapshotView.from_json_dict(snapshot_payload)
    assert view.version == "2.0"
    assert len(view.entries) == 2

    # Round-trip в новый registry (использует TypeAdapter validation).
    fresh = ServiceSchemaRegistry()
    fresh.from_snapshot(view.to_json_dict())

    fresh_summary = fresh.summary()
    assert fresh_summary["route"] == 1
    assert fresh_summary["processor"] == 1
    assert fresh_summary["workflow"] == 0
    restored = fresh.get(SchemaKind.ROUTE, "orders.create")
    assert restored is not None
    assert restored.meta["protocol"] == "http"


def test_snapshot_view_rejects_bad_version() -> None:
    """``SnapshotView.from_json_dict`` отклоняет невалидную версию."""
    bad_payload: dict[str, Any] = {"version": "1.0", "entries": []}
    with pytest.raises(ValueError, match="Unsupported snapshot version"):
        SnapshotView.from_json_dict(bad_payload)


def test_snapshot_view_rejects_non_list_entries() -> None:
    """``SnapshotView.from_json_dict`` отклоняет ``entries`` не-list."""
    bad_payload: dict[str, Any] = {"version": "2.0", "entries": "not-a-list"}
    with pytest.raises(ValueError, match="entries"):
        SnapshotView.from_json_dict(bad_payload)


# ── TypeAdapter validation errors ───────────────────────────────────


def test_entry_from_dict_rejects_missing_kind() -> None:
    """``entry_from_dict`` без ``kind`` поднимает :class:`ValueError`."""
    adapter = SchemaTypedAdapter()
    with pytest.raises(ValueError, match="kind"):
        adapter.entry_from_dict({"name": "x"})


def test_entry_from_dict_rejects_unknown_kind() -> None:
    """``entry_from_dict`` с несуществующим ``kind`` поднимает :class:`ValueError`."""
    adapter = SchemaTypedAdapter()
    with pytest.raises(ValueError):
        adapter.entry_from_dict({"kind": "unknown_kind", "name": "x"})


def test_entry_from_dict_rejects_empty_name() -> None:
    """``entry_from_dict`` с пустым ``name`` поднимает :class:`ValueError`."""
    adapter = SchemaTypedAdapter()
    with pytest.raises(ValueError, match="name"):
        adapter.entry_from_dict({"kind": "route", "name": ""})


def test_entry_from_dict_rejects_non_dict_spec_schema() -> None:
    """``entry_from_dict`` нормализует non-dict ``spec_schema`` → ``None``."""
    adapter = SchemaTypedAdapter()
    payload: dict[str, Any] = {
        "kind": "route",
        "name": "x",
        "spec_schema": "not-a-dict",  # type: ignore[typeddict-item]
    }
    # Sanitization: non-dict становится None (а не ValidationError).
    entry = adapter.entry_from_dict(payload)
    assert entry.spec_schema is None


def test_validate_snapshot_raises_validation_error_on_non_dict() -> None:
    """``validate_snapshot`` отклоняет не-dict payload через TypeAdapter."""
    reg = ServiceSchemaRegistry()
    with pytest.raises(ValidationError):
        reg.schema_view.validate_snapshot(["not", "a", "dict"])  # type: ignore[arg-type]


# ── schema_view property ────────────────────────────────────────────


def test_schema_view_property_returns_cached_adapter() -> None:
    """``ServiceSchemaRegistry.schema_view`` возвращает cached singleton."""
    reg = ServiceSchemaRegistry()
    view_a = reg.schema_view
    view_b = reg.schema_view
    assert view_a is view_b
    assert isinstance(view_a, SchemaTypedAdapter)


def test_schema_view_validates_registry_snapshot_round_trip() -> None:
    """``schema_view`` интегрируется с ``from_snapshot`` (D-A5-01 fix)."""
    reg = ServiceSchemaRegistry()
    entry = SchemaEntry(
        kind=SchemaKind.ACTION,
        name="orders.add",
        spec_schema={"type": "object"},
        meta={"tier": 2},
    )
    reg.register(entry)

    payload = reg.to_snapshot()
    # Прямой TypeAdapter call через schema_view (boundary validator).
    validated = reg.schema_view.validate_snapshot(payload)
    assert validated["version"] == CURRENT_SNAPSHOT_VERSION
    assert len(validated["entries"]) == 1

    restored_entry = reg.schema_view.entry_from_dict(validated["entries"][0])
    assert restored_entry == entry
