"""W25.3 — Unit-тест V1ToV2Migration."""

# ruff: noqa: S101

from __future__ import annotations

from src.dsl.versioning.migrations_v1_to_v2 import V1ToV2Migration


def test_migration_appends_v1_marker() -> None:
    spec = {"route_id": "demo", "_migrated_from": ["v0"]}
    out = V1ToV2Migration().migrate(spec)
    assert out["_migrated_from"] == ["v0", "v1"]


def test_migration_creates_history_when_missing() -> None:
    out = V1ToV2Migration().migrate({"route_id": "x"})
    assert out["_migrated_from"] == ["v1"]


def test_migration_does_not_duplicate_v1_marker() -> None:
    spec = {"route_id": "x", "_migrated_from": ["v0", "v1"]}
    out = V1ToV2Migration().migrate(spec)
    assert out["_migrated_from"] == ["v0", "v1"]


def test_migration_attributes() -> None:
    m = V1ToV2Migration()
    assert m.from_version == "v1"
    assert m.to_version == "v2"
