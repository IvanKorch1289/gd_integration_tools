"""Unit-тесты RouteHotReloader (Sprint 9 K3 W1)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from src.backend.services.routes.hot_reloader import ReloadEvent, RouteHotReloader


class _FakeLoader:
    def __init__(self) -> None:
        self.loaded_paths: list[Path] = []
        self.unloaded_names: list[str] = []
        self.full_reloads = 0
        self._fail_load = False

    def _load_one(self, manifest_path: Path) -> None:
        if self._fail_load:
            raise ValueError("invalid manifest")
        self.loaded_paths.append(manifest_path)

    async def unload_one(self, route_name: str) -> None:
        self.unloaded_names.append(route_name)

    async def unload_all(self) -> None:
        self.full_reloads += 1

    async def discover_and_load(self) -> tuple:  # noqa: ANN401
        return ()


@pytest.mark.asyncio
async def test_reloader_disabled_does_not_start() -> None:
    reloader = RouteHotReloader(
        loader=_FakeLoader(),
        routes_root=Path("/tmp"),
        enabled=False,
    )
    await reloader.start()
    assert reloader._task is None
    await reloader.stop()


@pytest.mark.asyncio
async def test_reload_one_modified_success(tmp_path: Path) -> None:
    routes_root = tmp_path / "routes"
    route_dir = routes_root / "my_route"
    route_dir.mkdir(parents=True)
    manifest = route_dir / "route.toml"
    manifest.write_text("name = 'my_route'\nversion = '0.1.0'\n")

    loader = _FakeLoader()
    events: list[ReloadEvent] = []
    reloader = RouteHotReloader(
        loader=loader,
        routes_root=routes_root,
        enabled=True,
        debounce_seconds=0.0,
        on_event=events.append,
    )
    await reloader._reload_one("my_route")
    assert manifest in loader.loaded_paths
    assert "my_route" in loader.unloaded_names
    assert events[0].route_name == "my_route"
    assert events[0].change_kind == "modified"
    assert events[0].success is True


@pytest.mark.asyncio
async def test_reload_one_removed_unloads(tmp_path: Path) -> None:
    routes_root = tmp_path / "routes"
    routes_root.mkdir()
    # route не существует — symbolizes removal
    loader = _FakeLoader()
    events: list[ReloadEvent] = []
    reloader = RouteHotReloader(
        loader=loader,
        routes_root=routes_root,
        enabled=True,
        debounce_seconds=0.0,
        on_event=events.append,
    )
    await reloader._reload_one("ghost_route")
    assert "ghost_route" in loader.unloaded_names
    assert events[0].change_kind == "removed"
    assert events[0].success is True


@pytest.mark.asyncio
async def test_reload_one_failed_records_error(tmp_path: Path) -> None:
    routes_root = tmp_path / "routes"
    (routes_root / "bad").mkdir(parents=True)
    (routes_root / "bad" / "route.toml").write_text("garbage")

    loader = _FakeLoader()
    loader._fail_load = True
    events: list[ReloadEvent] = []
    reloader = RouteHotReloader(
        loader=loader,
        routes_root=routes_root,
        enabled=True,
        debounce_seconds=0.0,
        on_event=events.append,
    )
    await reloader._reload_one("bad")
    assert events[0].success is False
    assert "invalid manifest" in (events[0].error or "")


def test_extract_route_names_from_changes(tmp_path: Path) -> None:
    routes_root = tmp_path / "routes"
    routes_root.mkdir()
    reloader = RouteHotReloader(loader=_FakeLoader(), routes_root=routes_root)
    changes = {
        (1, str(routes_root / "route_a" / "route.toml")),
        (2, str(routes_root / "route_b" / "spec.dsl.yaml")),
        (1, str(routes_root / "route_a" / "spec.dsl.yaml")),
    }
    names = reloader._extract_route_names(changes)
    assert names == {"route_a", "route_b"}


@pytest.mark.asyncio
async def test_per_route_lock_serializes(tmp_path: Path) -> None:
    routes_root = tmp_path / "routes"
    (routes_root / "concurrent").mkdir(parents=True)
    (routes_root / "concurrent" / "route.toml").write_text("name='x'")

    class _SlowLoader(_FakeLoader):
        def __init__(self) -> None:
            super().__init__()
            self.in_flight = 0
            self.max_concurrent = 0

        async def unload_one(self, route_name: str) -> None:
            self.in_flight += 1
            self.max_concurrent = max(self.max_concurrent, self.in_flight)
            await asyncio.sleep(0.02)
            self.in_flight -= 1
            await super().unload_one(route_name)

    loader = _SlowLoader()
    reloader = RouteHotReloader(
        loader=loader,
        routes_root=routes_root,
        enabled=True,
        debounce_seconds=0.0,
    )
    await asyncio.gather(
        reloader._reload_one("concurrent"),
        reloader._reload_one("concurrent"),
    )
    assert loader.max_concurrent == 1  # serialized through per-route lock
