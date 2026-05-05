"""W25.3 — Unit-тесты MigrationRegistry: find_path / apply / circular paths."""

# ruff: noqa: S101

from __future__ import annotations

from typing import Any

import pytest

from src.backend.dsl.versioning.migrations import (
    MigrationError,
    MigrationRegistry,
    apply_migrations,
)


class _NoOpMigration:
    def __init__(self, src: str, dst: str) -> None:
        self.from_version = src
        self.to_version = dst

    def migrate(self, spec: dict[str, Any]) -> dict[str, Any]:
        result = dict(spec)
        history = list(result.get("_migrated_from", []))
        history.append(self.from_version)
        result["_migrated_from"] = history
        return result


def test_register_duplicate_edge_raises() -> None:
    reg = MigrationRegistry()
    reg.register(_NoOpMigration("v0", "v1"))
    with pytest.raises(ValueError):
        reg.register(_NoOpMigration("v0", "v1"))


def test_find_path_self_returns_empty() -> None:
    reg = MigrationRegistry()
    reg.register(_NoOpMigration("v0", "v1"))
    assert reg.find_path("v0", "v0") == []


def test_find_path_chain_two_hops() -> None:
    reg = MigrationRegistry()
    reg.register(_NoOpMigration("v0", "v1"))
    reg.register(_NoOpMigration("v1", "v2"))
    chain = reg.find_path("v0", "v2")
    assert [m.to_version for m in chain] == ["v1", "v2"]


def test_find_path_no_route_raises() -> None:
    reg = MigrationRegistry()
    reg.register(_NoOpMigration("v0", "v1"))
    with pytest.raises(MigrationError):
        reg.find_path("v0", "v9")


def test_find_path_unreachable_target_raises_even_with_unrelated_edges() -> None:
    reg = MigrationRegistry()
    reg.register(_NoOpMigration("v0", "v1"))
    reg.register(_NoOpMigration("v3", "v4"))
    with pytest.raises(MigrationError):
        reg.find_path("v0", "v4")


def test_apply_migrations_chains_history_marker() -> None:
    reg = MigrationRegistry()
    reg.register(_NoOpMigration("v0", "v1"))
    reg.register(_NoOpMigration("v1", "v2"))
    spec = {"route_id": "x", "apiVersion": "v0"}
    out = apply_migrations(spec, target_version="v2", registry=reg)
    assert out["apiVersion"] == "v2"
    assert out["_migrated_from"] == ["v0", "v1"]


def test_apply_migrations_default_legacy_when_field_missing() -> None:
    reg = MigrationRegistry()
    reg.register(_NoOpMigration("v0", "v1"))
    reg.register(_NoOpMigration("v1", "v2"))
    spec = {"route_id": "x"}  # apiVersion отсутствует — считается v0
    out = apply_migrations(spec, target_version="v2", registry=reg)
    assert out["apiVersion"] == "v2"
    assert out["_migrated_from"] == ["v0", "v1"]


def test_apply_migrations_does_not_mutate_input() -> None:
    reg = MigrationRegistry()
    reg.register(_NoOpMigration("v0", "v1"))
    spec = {"route_id": "x", "apiVersion": "v0"}
    apply_migrations(spec, target_version="v1", registry=reg)
    assert spec == {"route_id": "x", "apiVersion": "v0"}


def test_apply_migrations_target_equals_current_returns_marked() -> None:
    reg = MigrationRegistry()
    spec = {"route_id": "x", "apiVersion": "v2"}
    out = apply_migrations(spec, target_version="v2", registry=reg)
    assert out["apiVersion"] == "v2"
