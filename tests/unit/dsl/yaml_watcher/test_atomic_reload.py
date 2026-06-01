"""W25.1 — Unit-тесты атомарности reload в DSLYamlWatcher."""

# ruff: noqa: S101

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from src.backend.dsl.commands.registry import RouteRegistry
from src.backend.dsl.yaml_watcher import DSLYamlWatcher


class _StubPipeline:
    def __init__(self, route_id: str) -> None:
        self.route_id = route_id
        self.feature_flag: str | None = None


def test_invalid_yaml_keeps_registry_unchanged(tmp_path: Path) -> None:
    """Если loader падает на одном файле — registry не теряет старые routes."""
    registry = RouteRegistry()
    registry.register(_StubPipeline("baseline.route"))
    initial = registry.list_routes()

    good = tmp_path / "good.yaml"
    bad = tmp_path / "bad.yaml"
    good.write_text("route_id: ok\n", encoding="utf-8")
    bad.write_text("route_id: err\n", encoding="utf-8")

    def loader(path: Path) -> Any:
        if path.name == "bad.yaml":
            raise ValueError("intentional")
        return _StubPipeline("ok")

    watcher = DSLYamlWatcher(
        routes_dir=tmp_path, route_registry=registry, loader=loader, debounce_ms=10
    )

    report = watcher._sync_reload_all()
    assert report["loaded"] == 0
    assert any("intentional" in e for e in report["errors"])

    assert registry.list_routes() == initial
    assert "ok" not in registry.list_routes()


def test_successful_reload_replaces_routes(tmp_path: Path) -> None:
    """Успешный reload регистрирует все YAML-маршруты."""
    registry = RouteRegistry()
    yaml1 = tmp_path / "alpha.yaml"
    yaml2 = tmp_path / "beta.yaml"
    yaml1.write_text("route_id: alpha\n", encoding="utf-8")
    yaml2.write_text("route_id: beta\n", encoding="utf-8")

    def loader(path: Path) -> Any:
        rid = path.stem
        return _StubPipeline(rid)

    watcher = DSLYamlWatcher(
        routes_dir=tmp_path, route_registry=registry, loader=loader, debounce_ms=10
    )
    report = watcher._sync_reload_all()
    assert report["loaded"] == 2
    assert set(registry.list_routes()) == {"alpha", "beta"}


def test_deletion_unregisters_route(tmp_path: Path) -> None:
    """Удалённый YAML → route_id уходит из registry."""
    registry = RouteRegistry()

    yaml1 = tmp_path / "a.yaml"
    yaml1.write_text("route_id: a\n", encoding="utf-8")

    def loader(path: Path) -> Any:
        return _StubPipeline(path.stem)

    watcher = DSLYamlWatcher(
        routes_dir=tmp_path, route_registry=registry, loader=loader, debounce_ms=10
    )
    watcher._sync_reload_all()
    assert "a" in registry.list_routes()

    yaml1.unlink()
    watcher._sync_reload_all()
    assert "a" not in registry.list_routes()


@pytest.mark.asyncio
async def test_reload_all_async_wraps_sync(tmp_path: Path) -> None:
    registry = RouteRegistry()
    (tmp_path / "x.yaml").write_text("route_id: x\n", encoding="utf-8")

    def loader(path: Path) -> Any:
        return _StubPipeline(path.stem)

    watcher = DSLYamlWatcher(
        routes_dir=tmp_path, route_registry=registry, loader=loader, debounce_ms=10
    )
    report = await watcher.reload_all()
    assert report["loaded"] == 1
    assert "x" in registry.list_routes()
