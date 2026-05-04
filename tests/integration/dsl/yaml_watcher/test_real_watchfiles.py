"""Wave B — Integration-тесты DSLYamlWatcher поверх ``watchfiles.awatch``."""

# ruff: noqa: S101

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from src.dsl.commands.registry import RouteRegistry
from src.dsl.yaml_watcher import DSLYamlWatcher


class _StubPipeline:
    def __init__(self, route_id: str) -> None:
        self.route_id = route_id
        self.feature_flag: str | None = None


async def _wait_until(predicate, timeout: float = 5.0, step: float = 0.05) -> bool:
    elapsed = 0.0
    while elapsed < timeout:
        if predicate():
            return True
        await asyncio.sleep(step)
        elapsed += step
    return False


@pytest.mark.asyncio
async def test_watcher_registers_new_yaml_file(tmp_path: Path) -> None:
    """Создание нового YAML → watcher регистрирует route в течение секунды."""
    registry = RouteRegistry()

    def loader(path: Path) -> Any:
        return _StubPipeline(path.stem)

    watcher = DSLYamlWatcher(
        routes_dir=tmp_path, route_registry=registry, loader=loader, debounce_ms=80
    )
    await watcher.start()
    # awatch подписывается асинхронно; даём ему успеть до первой записи.
    await asyncio.sleep(0.3)
    try:
        new_yaml = tmp_path / "fresh.yaml"
        new_yaml.write_text("route_id: fresh\n", encoding="utf-8")

        ok = await _wait_until(lambda: "fresh" in registry.list_routes(), timeout=4.0)
        assert ok, f"route не появился: {registry.list_routes()}"
    finally:
        await watcher.stop()


@pytest.mark.asyncio
async def test_watcher_unregisters_deleted_yaml(tmp_path: Path) -> None:
    """Удаление YAML → route уходит из registry."""
    registry = RouteRegistry()

    def loader(path: Path) -> Any:
        return _StubPipeline(path.stem)

    initial = tmp_path / "alpha.yaml"
    initial.write_text("route_id: alpha\n", encoding="utf-8")

    watcher = DSLYamlWatcher(
        routes_dir=tmp_path, route_registry=registry, loader=loader, debounce_ms=80
    )
    await watcher.start()
    await asyncio.sleep(0.3)  # awatch warmup
    try:
        assert "alpha" in registry.list_routes()
        initial.unlink()

        ok = await _wait_until(
            lambda: "alpha" not in registry.list_routes(), timeout=4.0
        )
        assert ok, f"route не удалён: {registry.list_routes()}"
    finally:
        await watcher.stop()


@pytest.mark.asyncio
async def test_watcher_invalid_yaml_does_not_break_registry(tmp_path: Path) -> None:
    """Невалидный YAML → snapshot откатывается, существующие routes живы."""
    registry = RouteRegistry()
    registry.register(_StubPipeline("baseline"))

    invalid_marker = "INVALID"

    def loader(path: Path) -> Any:
        text = path.read_text(encoding="utf-8")
        if invalid_marker in text:
            raise ValueError("invalid YAML by marker")
        return _StubPipeline(path.stem)

    watcher = DSLYamlWatcher(
        routes_dir=tmp_path, route_registry=registry, loader=loader, debounce_ms=80
    )
    await watcher.start()
    await asyncio.sleep(0.3)  # awatch warmup
    try:
        bad = tmp_path / "broken.yaml"
        bad.write_text(f"route_id: broken\n# {invalid_marker}\n", encoding="utf-8")

        # Дать время watcher'у обработать.
        await asyncio.sleep(0.6)

        # baseline должен сохраниться, broken не зарегистрирован.
        routes = registry.list_routes()
        assert "baseline" in routes
        assert "broken" not in routes
    finally:
        await watcher.stop()
