"""Wave B — Unit-тесты дебаунса DSLYamlWatcher (поверх ``watchfiles``).

Реальный дебаунс делегирован ``watchfiles.awatch(debounce=...)``.
Эти тесты проверяют, что watcher корректно вызывает ``_sync_reload_all``
ровно один раз на пакет ``changes`` от awatch и пропускает пакеты,
не содержащие YAML-файлов.
"""

# ruff: noqa: S101

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from src.backend.dsl import yaml_watcher as yaml_watcher_mod
from src.backend.dsl.yaml_watcher import DSLYamlWatcher


class _StubRegistry:
    def __init__(self) -> None:
        self._state: dict[str, Any] = {}

    def snapshot_state(self) -> dict[str, Any]:
        return dict(self._state)

    def restore_state(self, snap: dict[str, Any]) -> None:
        self._state = dict(snap)

    def register(self, pipeline: Any) -> None:
        self._state[pipeline.route_id] = pipeline

    def unregister(self, route_id: str) -> bool:
        return self._state.pop(route_id, None) is not None


def _fake_awatch(batches: list[set[tuple[int, str]]]):
    """Фабрика fake-awatch, эмитящая заранее заданные пачки изменений."""

    async def _gen(*args: Any, **kwargs: Any) -> AsyncIterator[set[tuple[int, str]]]:
        for batch in batches:
            yield batch
            await asyncio.sleep(0)

    return _gen


@pytest.mark.asyncio
async def test_one_batch_one_reload(tmp_path: Path, monkeypatch) -> None:
    """Один пачковый event от awatch → один вызов ``_sync_reload_all``."""
    registry = _StubRegistry()
    watcher = DSLYamlWatcher(
        routes_dir=tmp_path,
        route_registry=registry,
        loader=lambda p: None,
        debounce_ms=10,
    )

    reload_calls: list[int] = []

    def fake_sync_reload_all() -> dict[str, Any]:
        reload_calls.append(1)
        return {"loaded": 0, "errors": []}

    monkeypatch.setattr(watcher, "_sync_reload_all", fake_sync_reload_all)
    monkeypatch.setattr(
        yaml_watcher_mod,
        "awatch",
        _fake_awatch([{(1, str(tmp_path / "r.yaml"))}]),
    )

    consumer = asyncio.create_task(watcher._consume_loop())
    await asyncio.sleep(0.05)
    consumer.cancel()
    try:
        await consumer
    except asyncio.CancelledError:
        pass

    assert reload_calls == [1]


@pytest.mark.asyncio
async def test_two_batches_two_reloads(tmp_path: Path, monkeypatch) -> None:
    """Две независимые пачки awatch → два reload."""
    registry = _StubRegistry()
    watcher = DSLYamlWatcher(
        routes_dir=tmp_path,
        route_registry=registry,
        loader=lambda p: None,
        debounce_ms=10,
    )

    reload_calls: list[int] = []

    def fake_sync_reload_all() -> dict[str, Any]:
        reload_calls.append(1)
        return {"loaded": 0, "errors": []}

    monkeypatch.setattr(watcher, "_sync_reload_all", fake_sync_reload_all)
    monkeypatch.setattr(
        yaml_watcher_mod,
        "awatch",
        _fake_awatch(
            [
                {(1, str(tmp_path / "a.yaml"))},
                {(2, str(tmp_path / "b.yaml"))},
            ]
        ),
    )

    consumer = asyncio.create_task(watcher._consume_loop())
    await asyncio.sleep(0.05)
    consumer.cancel()
    try:
        await consumer
    except asyncio.CancelledError:
        pass

    assert len(reload_calls) == 2


@pytest.mark.asyncio
async def test_non_yaml_change_is_ignored(tmp_path: Path, monkeypatch) -> None:
    """Пачка без YAML-путей → reload не вызывается."""
    registry = _StubRegistry()
    watcher = DSLYamlWatcher(
        routes_dir=tmp_path,
        route_registry=registry,
        loader=lambda p: None,
        debounce_ms=10,
    )

    reload_calls: list[int] = []

    def fake_sync_reload_all() -> dict[str, Any]:
        reload_calls.append(1)
        return {"loaded": 0, "errors": []}

    monkeypatch.setattr(watcher, "_sync_reload_all", fake_sync_reload_all)
    monkeypatch.setattr(
        yaml_watcher_mod,
        "awatch",
        _fake_awatch([{(1, str(tmp_path / "noise.txt"))}]),
    )

    consumer = asyncio.create_task(watcher._consume_loop())
    await asyncio.sleep(0.05)
    consumer.cancel()
    try:
        await consumer
    except asyncio.CancelledError:
        pass

    assert reload_calls == []
