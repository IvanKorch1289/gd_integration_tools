"""W25.1 — Unit-тесты debounce-логики DSLYamlWatcher."""

# ruff: noqa: S101

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from src.dsl.yaml_watcher import DSLYamlWatcher


class _StubRegistry:
    def __init__(self) -> None:
        self.snapshots: list[dict[str, Any]] = []
        self.restored: list[dict[str, Any]] = []
        self._state: dict[str, Any] = {}

    def snapshot_state(self) -> dict[str, Any]:
        snap = dict(self._state)
        self.snapshots.append(snap)
        return snap

    def restore_state(self, snap: dict[str, Any]) -> None:
        self._state = dict(snap)
        self.restored.append(dict(snap))

    def register(self, pipeline: Any) -> None:
        self._state[pipeline.route_id] = pipeline

    def unregister(self, route_id: str) -> bool:
        return self._state.pop(route_id, None) is not None


@pytest.mark.asyncio
async def test_consume_loop_debounces_burst_to_single_reload(
    tmp_path: Path, monkeypatch
) -> None:
    """Шторм событий за окно дебаунса вызывает ровно один reload."""
    registry = _StubRegistry()
    watcher = DSLYamlWatcher(
        routes_dir=tmp_path,
        route_registry=registry,
        loader=lambda p: None,  # не должен вызываться при стабе
        debounce_ms=80,
    )

    reload_calls: list[int] = []

    def fake_sync_reload_all() -> dict[str, Any]:
        reload_calls.append(1)
        return {"loaded": 0, "errors": []}

    monkeypatch.setattr(watcher, "_sync_reload_all", fake_sync_reload_all)

    queue: asyncio.Queue[tuple[str, str]] = asyncio.Queue()
    watcher._queue = queue  # type: ignore[attr-defined]

    consumer = asyncio.create_task(watcher._consume_loop())

    for _ in range(10):
        await queue.put(("modified", str(tmp_path / "r.yaml")))
        await asyncio.sleep(0.005)

    # Ждём окно тишины + запас.
    await asyncio.sleep(0.25)

    consumer.cancel()
    try:
        await consumer
    except asyncio.CancelledError:
        pass

    assert len(reload_calls) == 1, (
        f"Ожидался один reload, фактически: {len(reload_calls)}"
    )


@pytest.mark.asyncio
async def test_consume_loop_separates_distant_bursts(
    tmp_path: Path, monkeypatch
) -> None:
    """Два события с интервалом > debounce → два отдельных reload."""
    registry = _StubRegistry()
    watcher = DSLYamlWatcher(
        routes_dir=tmp_path,
        route_registry=registry,
        loader=lambda p: None,
        debounce_ms=50,
    )

    reload_calls: list[int] = []

    def fake_sync_reload_all() -> dict[str, Any]:
        reload_calls.append(1)
        return {"loaded": 0, "errors": []}

    monkeypatch.setattr(watcher, "_sync_reload_all", fake_sync_reload_all)

    queue: asyncio.Queue[tuple[str, str]] = asyncio.Queue()
    watcher._queue = queue  # type: ignore[attr-defined]
    consumer = asyncio.create_task(watcher._consume_loop())

    await queue.put(("modified", "a"))
    await asyncio.sleep(0.2)  # дебаунс уже прошёл, reload состоялся
    await queue.put(("modified", "b"))
    await asyncio.sleep(0.2)

    consumer.cancel()
    try:
        await consumer
    except asyncio.CancelledError:
        pass

    assert len(reload_calls) == 2
