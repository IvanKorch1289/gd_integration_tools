"""W23.3 — FileWatcherSource (integration через tmp_path)."""

# ruff: noqa: S101

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from src.backend.core.interfaces.source import SourceEvent
from src.backend.infrastructure.sources.file_watcher import FileWatcherSource


@pytest.mark.asyncio
async def test_watcher_emits_on_create(tmp_path: Path) -> None:
    captured: list[SourceEvent] = []

    async def cb(ev: SourceEvent) -> None:
        captured.append(ev)

    src = FileWatcherSource(tmp_path, debounce=0.05)
    await src.start(cb)
    try:
        await asyncio.sleep(0.1)
        target = tmp_path / "data.csv"
        target.write_text("a,b\n1,2\n")
        await asyncio.sleep(0.6)
    finally:
        await src.stop()

    assert any("data.csv" in (ev.payload or {}).get("path", "") for ev in captured), (
        f"events captured: {[(e.payload) for e in captured]}"
    )


@pytest.mark.asyncio
async def test_watcher_filters_by_pattern(tmp_path: Path) -> None:
    captured: list[SourceEvent] = []

    async def cb(ev: SourceEvent) -> None:
        captured.append(ev)

    async def filter_csv(change, path):
        return str(path).endswith(".csv")

    src = FileWatcherSource(tmp_path, debounce=0.05, watch_filter=filter_csv)
    await src.start(cb)
    try:
        await asyncio.sleep(0.1)
        (tmp_path / "ignored.txt").write_text("nope")
        await asyncio.sleep(0.6)
    finally:
        await src.stop()

    paths = [(e.payload or {}).get("path", "") for e in captured]
    assert all("ignored.txt" not in p for p in paths)


@pytest.mark.asyncio
async def test_double_start_rejected(tmp_path: Path) -> None:
    src = FileWatcherSource(tmp_path)
    await src.start(_noop_cb)
    try:
        with pytest.raises(RuntimeError):
            await src.start(_noop_cb)
    finally:
        await src.stop()


async def _noop_cb(ev: SourceEvent) -> None:
    return None
