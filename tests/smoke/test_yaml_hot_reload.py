"""Wave B — smoke-тест hot-reload DSL YAML routes (через ``watchfiles``).

Тест моделирует реальный сценарий: пользователь кладёт YAML в watch-каталог,
watcher регистрирует route через ``RouteRegistry``; затем YAML удаляется —
watcher вычищает route. Дебаунс делегирован ``watchfiles.awatch``.
"""

# ruff: noqa: S101

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Callable

import pytest

from src.backend.dsl.commands.registry import RouteRegistry
from src.backend.dsl.yaml_watcher import DSLYamlWatcher


class _StubPipeline:
    def __init__(self, route_id: str) -> None:
        self.route_id = route_id
        self.feature_flag: str | None = None


async def _wait_until(
    predicate: Callable[[], bool], timeout: float = 5.0, step: float = 0.05
) -> bool:
    elapsed = 0.0
    while elapsed < timeout:
        if predicate():
            return True
        await asyncio.sleep(step)
        elapsed += step
    return False


@pytest.mark.asyncio
async def test_yaml_hot_reload_lifecycle(tmp_path: Path) -> None:
    """E2E: создать → ждать register; модифицировать → ждать reload;
    удалить → ждать unregister."""
    registry = RouteRegistry()
    load_calls: list[Path] = []

    def loader(path: Path) -> Any:
        load_calls.append(path)
        return _StubPipeline(path.stem)

    watcher = DSLYamlWatcher(
        routes_dir=tmp_path,
        route_registry=registry,
        loader=loader,
        debounce_ms=80,
    )

    await watcher.start()
    # awatch подписывается асинхронно; даём ему успеть до первой записи.
    await asyncio.sleep(0.3)
    try:
        # 1. Создание нового YAML.
        new_yaml = tmp_path / "demo.yaml"
        new_yaml.write_text("route_id: demo\n", encoding="utf-8")
        registered = await _wait_until(
            lambda: "demo" in registry.list_routes(), timeout=4.0
        )
        assert registered, f"route не появился: {registry.list_routes()}"

        # 2. Модификация (touch + изменение содержимого) → reload.
        load_count_before = len(load_calls)
        new_yaml.write_text("route_id: demo\n# changed\n", encoding="utf-8")
        reloaded = await _wait_until(
            lambda: len(load_calls) > load_count_before, timeout=4.0
        )
        assert reloaded, "повторная загрузка не зафиксирована"

        # 3. Удаление YAML → unregister.
        new_yaml.unlink()
        removed = await _wait_until(
            lambda: "demo" not in registry.list_routes(), timeout=4.0
        )
        assert removed, f"route не удалён: {registry.list_routes()}"
    finally:
        await watcher.stop()
