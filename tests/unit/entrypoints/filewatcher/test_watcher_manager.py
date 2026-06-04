"""Unit tests for watcher_manager (Wave B: watchfiles-based file watcher)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.entrypoints.filewatcher.watcher_manager import (
    WatcherManager,
    WatcherSpec,
    watcher_manager,
)


@pytest.fixture
def temp_dir(tmp_path: Path) -> Path:
    """Returns a temporary directory for watcher tests."""
    return tmp_path


@pytest.fixture
def manager() -> WatcherManager:
    """Returns a fresh WatcherManager instance."""
    return WatcherManager()


# ─── WatcherSpec ─────────────────────────────────────────────────────────────


def test_watcher_spec_defaults() -> None:
    """WatcherSpec has sensible defaults."""
    spec = WatcherSpec()
    assert spec.directory == ""
    assert spec.pattern == "*"
    assert spec.poll_interval == 5.0
    assert spec.active is True
    assert len(spec.id) == 12


def test_watcher_spec_custom_values() -> None:
    """WatcherSpec accepts custom values."""
    spec = WatcherSpec(directory="/tmp", pattern="*.csv", route_id="r1", poll_interval=1.0, active=False)
    assert spec.directory == "/tmp"
    assert spec.pattern == "*.csv"
    assert spec.route_id == "r1"
    assert spec.poll_interval == 1.0
    assert spec.active is False


# ─── add ─────────────────────────────────────────────────────────────────────


def test_add_creates_watcher(temp_dir: Path, manager: WatcherManager) -> None:
    """add creates and starts a watcher."""
    spec = WatcherSpec(directory=str(temp_dir), pattern="*.txt", route_id="r1")
    mock_registry = MagicMock()
    mock_task = MagicMock()
    mock_registry.create_task.return_value = mock_task

    with patch(
        "src.backend.entrypoints.filewatcher.watcher_manager.get_task_registry",
        return_value=mock_registry,
    ):
        result = manager.add(spec)

    assert result.id == spec.id
    assert result.directory == str(temp_dir)
    assert spec.id in manager._watchers
    mock_registry.create_task.assert_called_once()


def test_add_raises_on_missing_directory(manager: WatcherManager) -> None:
    """add raises ValueError when directory does not exist."""
    spec = WatcherSpec(directory="/nonexistent/path", pattern="*")
    with pytest.raises(ValueError, match="Директория не найдена"):
        manager.add(spec)


# ─── remove ──────────────────────────────────────────────────────────────────


def test_remove_stops_watcher(temp_dir: Path, manager: WatcherManager) -> None:
    """remove stops and deletes a watcher."""
    spec = WatcherSpec(directory=str(temp_dir), pattern="*", route_id="r1")
    mock_registry = MagicMock()
    mock_task = MagicMock()
    mock_task.done.return_value = False
    mock_registry.create_task.return_value = mock_task

    with patch(
        "src.backend.entrypoints.filewatcher.watcher_manager.get_task_registry",
        return_value=mock_registry,
    ):
        manager.add(spec)

    manager.remove(spec.id)
    assert spec.id not in manager._watchers
    mock_task.cancel.assert_called_once()


def test_remove_raises_on_missing(manager: WatcherManager) -> None:
    """remove raises KeyError when watcher not found."""
    with pytest.raises(KeyError, match="Watcher missing не найден"):
        manager.remove("missing")


# ─── list_watchers ───────────────────────────────────────────────────────────


def test_list_watchers(temp_dir: Path, manager: WatcherManager) -> None:
    """list_watchers returns active watcher specs."""
    spec = WatcherSpec(directory=str(temp_dir), pattern="*.csv", route_id="r2")
    mock_registry = MagicMock()
    mock_registry.create_task.return_value = MagicMock()

    with patch(
        "src.backend.entrypoints.filewatcher.watcher_manager.get_task_registry",
        return_value=mock_registry,
    ):
        manager.add(spec)

    result = manager.list_watchers()
    assert len(result) == 1
    assert result[0]["id"] == spec.id
    assert result[0]["directory"] == str(temp_dir)
    assert result[0]["pattern"] == "*.csv"


def test_list_watchers_empty(manager: WatcherManager) -> None:
    """list_watchers returns empty list when no watchers."""
    assert manager.list_watchers() == []


# ─── stop_all ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_stop_all_clears_watchers(temp_dir: Path, manager: WatcherManager) -> None:
    """stop_all stops all watchers and clears state."""
    spec1 = WatcherSpec(directory=str(temp_dir), pattern="*", route_id="r1")
    spec2 = WatcherSpec(directory=str(temp_dir), pattern="*.log", route_id="r2")
    mock_registry = MagicMock()
    mock_task = MagicMock()
    mock_task.done.return_value = False
    mock_registry.create_task.return_value = mock_task

    with patch(
        "src.backend.entrypoints.filewatcher.watcher_manager.get_task_registry",
        return_value=mock_registry,
    ):
        manager.add(spec1)
        manager.add(spec2)

    await manager.stop_all()
    assert manager.list_watchers() == []
    assert manager._tasks == {}
    assert manager._stop_events == {}


# ─── _watch_loop ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_watch_loop_dispatches_matching_file(temp_dir: Path, manager: WatcherManager) -> None:
    """_watch_loop dispatches when file matches pattern."""
    spec = WatcherSpec(directory=str(temp_dir), pattern="*.txt", route_id="r1")
    manager._watchers[spec.id] = spec
    stop_event = asyncio.Event()
    manager._stop_events[spec.id] = stop_event

    mock_dsl = AsyncMock()

    with patch(
        "src.backend.entrypoints.filewatcher.watcher_manager.get_dsl_service",
        return_value=mock_dsl,
    ), patch(
        "src.backend.entrypoints.filewatcher.watcher_manager.awatch",
        return_value=async_generator_yielding((1, str(temp_dir / "test.txt"))),
    ):
        await manager._watch_loop(spec.id, stop_event)

    mock_dsl.dispatch.assert_awaited_once()
    call_kwargs = mock_dsl.dispatch.call_args[1]
    assert call_kwargs["route_id"] == "r1"
    assert call_kwargs["body"]["filename"] == "test.txt"


@pytest.mark.asyncio
async def test_watch_loop_skips_deleted(temp_dir: Path, manager: WatcherManager) -> None:
    """_watch_loop skips deleted files."""
    from watchfiles import Change

    spec = WatcherSpec(directory=str(temp_dir), pattern="*", route_id="r1")
    manager._watchers[spec.id] = spec
    stop_event = asyncio.Event()

    mock_dsl = AsyncMock()

    with patch(
        "src.backend.entrypoints.filewatcher.watcher_manager.get_dsl_service",
        return_value=mock_dsl,
    ), patch(
        "src.backend.entrypoints.filewatcher.watcher_manager.awatch",
        return_value=async_generator_yielding((Change.deleted, str(temp_dir / "gone.txt"))),
    ):
        await manager._watch_loop(spec.id, stop_event)

    mock_dsl.dispatch.assert_not_awaited()


@pytest.mark.asyncio
async def test_watch_loop_skips_non_matching_pattern(temp_dir: Path, manager: WatcherManager) -> None:
    """_watch_loop skips files not matching pattern."""
    spec = WatcherSpec(directory=str(temp_dir), pattern="*.csv", route_id="r1")
    manager._watchers[spec.id] = spec
    stop_event = asyncio.Event()

    mock_dsl = AsyncMock()

    with patch(
        "src.backend.entrypoints.filewatcher.watcher_manager.get_dsl_service",
        return_value=mock_dsl,
    ), patch(
        "src.backend.entrypoints.filewatcher.watcher_manager.awatch",
        return_value=async_generator_yielding((1, str(temp_dir / "test.txt"))),
    ):
        await manager._watch_loop(spec.id, stop_event)

    mock_dsl.dispatch.assert_not_awaited()


@pytest.mark.asyncio
async def test_watch_loop_exits_when_spec_removed(temp_dir: Path, manager: WatcherManager) -> None:
    """_watch_loop exits when spec is removed mid-flight."""
    spec = WatcherSpec(directory=str(temp_dir), pattern="*", route_id="r1")
    manager._watchers[spec.id] = spec
    stop_event = asyncio.Event()

    # Remove spec before loop processes anything
    async def _gen() -> Any:
        manager._watchers.pop(spec.id, None)
        yield (1, str(temp_dir / "test.txt"))

    with patch(
        "src.backend.entrypoints.filewatcher.watcher_manager.awatch",
        return_value=_gen(),
    ):
        await manager._watch_loop(spec.id, stop_event)

    # Should exit without error


@pytest.mark.asyncio
async def test_watch_loop_exits_when_inactive(temp_dir: Path, manager: WatcherManager) -> None:
    """_watch_loop exits when spec becomes inactive."""
    spec = WatcherSpec(directory=str(temp_dir), pattern="*", route_id="r1")
    manager._watchers[spec.id] = spec
    stop_event = asyncio.Event()

    async def _gen() -> Any:
        spec.active = False
        yield (1, str(temp_dir / "test.txt"))

    with patch(
        "src.backend.entrypoints.filewatcher.watcher_manager.awatch",
        return_value=_gen(),
    ):
        await manager._watch_loop(spec.id, stop_event)


# ─── _dispatch ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_dispatch_calls_dsl_service(manager: WatcherManager) -> None:
    """_dispatch sends file event to DSL service."""
    spec = WatcherSpec(directory="/tmp", pattern="*", route_id="r1")
    mock_dsl = AsyncMock()

    with patch(
        "src.backend.entrypoints.filewatcher.watcher_manager.get_dsl_service",
        return_value=mock_dsl,
    ):
        await manager._dispatch(spec, "w1", "/tmp/file.txt", "file.txt")

    mock_dsl.dispatch.assert_awaited_once_with(
        route_id="r1",
        body={"filename": "file.txt", "filepath": "/tmp/file.txt", "watcher_id": "w1"},
        headers={"x-source": "filewatcher", "x-watcher-id": "w1"},
    )


@pytest.mark.asyncio
async def test_dispatch_logs_exception(caplog: pytest.LogCaptureFixture, manager: WatcherManager) -> None:
    """_dispatch logs exception on DSL service failure."""
    spec = WatcherSpec(directory="/tmp", pattern="*", route_id="r1")
    mock_dsl = AsyncMock()
    mock_dsl.dispatch.side_effect = RuntimeError("dsl error")

    with patch(
        "src.backend.entrypoints.filewatcher.watcher_manager.get_dsl_service",
        return_value=mock_dsl,
    ), caplog.at_level("ERROR"):
        await manager._dispatch(spec, "w1", "/tmp/file.txt", "file.txt")

    assert "ошибка обработки" in caplog.text


# ─── singleton ───────────────────────────────────────────────────────────────


def test_watcher_manager_singleton() -> None:
    """watcher_manager is a singleton instance."""
    assert isinstance(watcher_manager, WatcherManager)


# ─── helpers ─────────────────────────────────────────────────────────────────


async def async_generator_yielding(*items: Any) -> Any:
    """Helper async generator that yields the provided items."""
    for item in items:
        yield {item}
