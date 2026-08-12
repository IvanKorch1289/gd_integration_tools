"""W25.1 — Unit-тесты атомарности reload в DSLYamlWatcher."""


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
        routes_dir=tmp_path, route_registry=registry, loader=loader, debounce_ms=10,
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
        routes_dir=tmp_path, route_registry=registry, loader=loader, debounce_ms=10,
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
        routes_dir=tmp_path, route_registry=registry, loader=loader, debounce_ms=10,
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
        routes_dir=tmp_path, route_registry=registry, loader=loader, debounce_ms=10,
    )
    report = await watcher.reload_all()
    assert report["loaded"] == 1
    assert "x" in registry.list_routes()


def test_partial_apply_multi_file_no_partial_state(tmp_path: Path) -> None:
    """Multi-file reload с падением в середине НЕ оставляет partial state в registry.

    Если loader падает на файле b.yaml (после успешного a.yaml), registry
    должен остаться идентичным pre-reload snapshot — ни a, ни b не должны
    попасть в реестр. Это и есть atomicity через ``snapshot_state`` /
    ``restore_state`` (см. ADR-0105).
    """
    registry = RouteRegistry()
    registry.register(_StubPipeline("baseline.route"))
    initial = registry.list_routes()

    for name in ("a.yaml", "b.yaml", "c.yaml"):
        (tmp_path / name).write_text(f"route_id: {name[0]}\n", encoding="utf-8")

    def loader(path: Path) -> Any:
        if path.name == "b.yaml":
            raise ValueError("mid-batch failure on b")
        return _StubPipeline(path.stem)

    watcher = DSLYamlWatcher(
        routes_dir=tmp_path, route_registry=registry, loader=loader, debounce_ms=10
    )

    report = watcher._sync_reload_all()

    # Полный rollback: registry как до reload.
    assert registry.list_routes() == initial
    assert "a" not in registry.list_routes()
    assert "b" not in registry.list_routes()
    assert "c" not in registry.list_routes()
    assert report["loaded"] == 0
    assert any("mid-batch failure on b" in e for e in report["errors"])


def test_partial_apply_incremental_rollback(tmp_path: Path) -> None:
    """Инкрементальный reload с ошибкой на одном из файлов откатывает snapshot.

    Если одновременно изменены 3 файла и loader падает на втором, snapshot
    восстанавливается полностью. Это проверяет, что ``_sync_reload_incremental``
    корректно вызывает ``registry.restore_state`` при исключении в середине
    батча.
    """
    registry = RouteRegistry()
    registry.register(_StubPipeline("baseline.route"))
    initial = registry.list_routes()

    for name in ("x.yaml", "y.yaml", "z.yaml"):
        (tmp_path / name).write_text(f"route_id: {name[0]}\n", encoding="utf-8")

    def loader(path: Path) -> Any:
        if path.name == "y.yaml":
            raise ValueError("intentional on y")
        return _StubPipeline(path.stem)

    watcher = DSLYamlWatcher(
        routes_dir=tmp_path, route_registry=registry, loader=loader, debounce_ms=10
    )

    # Симулируем инкрементальный reload с 3 изменениями.
    changes = {
        ("change", str(tmp_path / "x.yaml")),
        ("change", str(tmp_path / "y.yaml")),
        ("change", str(tmp_path / "z.yaml")),
    }
    watcher._sync_reload_incremental(changes)

    # Если snapshot/restore работает, registry остаётся в исходном состоянии.
    assert registry.list_routes() == initial
    assert "x" not in registry.list_routes()
    assert "y" not in registry.list_routes()
    assert "z" not in registry.list_routes()
