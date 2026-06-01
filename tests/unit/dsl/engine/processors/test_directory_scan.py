"""Unit tests for DirectoryScanProcessor (S35 GAP-INT-3)."""

# ruff: noqa: S101

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from typing import Any
from unittest.mock import AsyncMock

import pytest

# Ensure the test can import the module even before installation
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../../.."))

from src.backend.dsl.engine.exchange import Exchange, Message
from src.backend.dsl.engine.processors.fs_directory_scan import DirectoryScanProcessor


def _ex(body: Any = None, headers: dict[str, Any] | None = None) -> Exchange[Any]:
    return Exchange(in_message=Message(body=body, headers=headers or {}))


# =============================================================================
# Helper — create real files in a temp dir
# =============================================================================


def _tmpdir(files: list[str]) -> tuple[str, list[str]]:
    """Create a temp dir with the given relative file paths and return (dir, full_paths)."""
    tmp = tempfile.mkdtemp()
    created = []
    for rel in files:
        full = os.path.join(tmp, rel)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w") as fh:
            fh.write("x" * (hash(rel) % 100 + 1))
        created.append(full)
    return tmp, created


def _mtime(path: str) -> float:
    return os.stat(path).st_mtime


# =============================================================================
# Tests
# =============================================================================


@pytest.mark.asyncio
async def test_directory_scan_finds_matching_files() -> None:
    """Non-recursive scan returns only files matching the glob in the root."""
    tmp, created = _tmpdir(["a.csv", "b.csv", "c.txt"])
    try:
        proc = DirectoryScanProcessor(path=tmp, pattern="*.csv", recursive=False)
        ctx = AsyncMock()
        e = _ex()
        await proc.process(e, ctx)

        result = e.properties.get("directory_scan_result")
        assert result is not None
        assert isinstance(result, list)
        names = {entry["name"] for entry in result}
        assert names == {"a.csv", "b.csv"}
        assert "c.txt" not in names
        for entry in result:
            assert "path" in entry
            assert "name" in entry
            assert "size" in entry
            assert "mtime" in entry
    finally:
        shutil.rmtree(tmp)


@pytest.mark.asyncio
async def test_directory_scan_respects_max_files() -> None:
    """Setting max_files limits the returned list."""
    tmp, created = _tmpdir([f"file_{i}.txt" for i in range(10)])
    try:
        proc = DirectoryScanProcessor(path=tmp, pattern="*.txt", recursive=False, max_files=3)
        ctx = AsyncMock()
        e = _ex()
        await proc.process(e, ctx)

        result = e.properties.get("directory_scan_result")
        assert isinstance(result, list)
        assert len(result) == 3
    finally:
        shutil.rmtree(tmp)


@pytest.mark.asyncio
async def test_directory_scan_recursive() -> None:
    """Recursive scan finds files in subdirectories."""
    tmp, created = _tmpdir(["root.txt", "subdir/nested.csv", "subdir/deep/more.json"])
    try:
        proc = DirectoryScanProcessor(path=tmp, pattern="*.csv", recursive=True)
        ctx = AsyncMock()
        e = _ex()
        await proc.process(e, ctx)

        result = e.properties.get("directory_scan_result")
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["name"] == "nested.csv"
        assert "subdir" in result[0]["path"]
    finally:
        shutil.rmtree(tmp)


@pytest.mark.asyncio
async def test_directory_scan_sort_by_mtime() -> None:
    """Results are sorted by mtime when sort_by='mtime'."""
    tmp, created = _tmpdir(["old.txt", "new.txt"])
    try:
        # Ensure different mtimes: touch old first, new second
        old_path = os.path.join(tmp, "old.txt")
        new_path = os.path.join(tmp, "new.txt")
        os.utime(old_path, (0.0, 0.0))   # very old
        os.utime(new_path, (1e9, 1e9))  # recent

        proc = DirectoryScanProcessor(path=tmp, pattern="*.txt", recursive=False, sort_by="mtime")
        ctx = AsyncMock()
        e = _ex()
        await proc.process(e, ctx)

        result = e.properties.get("directory_scan_result")
        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0]["name"] == "old.txt"
        assert result[1]["name"] == "new.txt"
    finally:
        shutil.rmtree(tmp)


@pytest.mark.asyncio
async def test_directory_scan_sort_by_size() -> None:
    """Results are sorted by size when sort_by='size'."""
    tmp, created = _tmpdir(["small.txt", "big.txt"])
    try:
        small_path = os.path.join(tmp, "small.txt")
        big_path = os.path.join(tmp, "big.txt")
        with open(small_path, "w") as f:
            f.write("x")
        with open(big_path, "w") as f:
            f.write("x" * 200)

        proc = DirectoryScanProcessor(path=tmp, pattern="*.txt", recursive=False, sort_by="size")
        ctx = AsyncMock()
        e = _ex()
        await proc.process(e, ctx)

        result = e.properties.get("directory_scan_result")
        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0]["name"] == "small.txt"
        assert result[1]["name"] == "big.txt"
    finally:
        shutil.rmtree(tmp)


@pytest.mark.asyncio
async def test_directory_scan_no_path_provided() -> None:
    """Exchange fails gracefully when no path is set."""
    proc = DirectoryScanProcessor(path="", pattern="*")
    ctx = AsyncMock()
    e = _ex()
    await proc.process(e, ctx)

    assert e.status == "failed" or "no path" in str(e.error or "").lower()


@pytest.mark.asyncio
async def test_directory_scan_not_a_directory() -> None:
    """Fails when path points to a file, not a directory."""
    with tempfile.NamedTemporaryFile(delete=False) as tf:
        tf.write(b"hello")
        fake_path = tf.name
    try:
        proc = DirectoryScanProcessor(path=fake_path, pattern="*")
        ctx = AsyncMock()
        e = _ex()
        await proc.process(e, ctx)

        assert e.status == "failed" or "not a directory" in str(e.error or "").lower()
    finally:
        os.unlink(fake_path)
