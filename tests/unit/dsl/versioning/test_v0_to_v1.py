"""W25.3 — Unit-тест V0ToV1Migration."""

# ruff: noqa: S101

from __future__ import annotations

from src.dsl.versioning.migrations_v0_to_v1 import V0ToV1Migration


def test_migration_marks_history_and_keeps_payload() -> None:
    spec = {"route_id": "demo", "processors": [{"log": {"level": "info"}}]}
    migration = V0ToV1Migration()
    out = migration.migrate(spec)
    assert out["route_id"] == "demo"
    assert out["processors"] == spec["processors"]
    assert out["_migrated_from"] == ["v0"]


def test_migration_appends_to_existing_history() -> None:
    spec = {"route_id": "demo", "_migrated_from": ["legacy"]}
    out = V0ToV1Migration().migrate(spec)
    assert out["_migrated_from"] == ["legacy", "v0"]


def test_migration_attributes() -> None:
    m = V0ToV1Migration()
    assert m.from_version == "v0"
    assert m.to_version == "v1"
