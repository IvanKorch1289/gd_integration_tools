"""Unit-тесты DiskCacheBackend (S133 W4)."""

# ruff: noqa: S101

from __future__ import annotations

from pathlib import Path

import pytest

from src.backend.infrastructure.cache.backends.disk import DiskCacheBackend


@pytest.fixture()
def backend(tmp_path: Path) -> DiskCacheBackend:
    return DiskCacheBackend(base_path=tmp_path / "disk_cache")


@pytest.mark.asyncio
async def test_get_set_delete(backend: DiskCacheBackend) -> None:
    assert await backend.get("k1") is None
    await backend.set("k1", b"value1")
    assert await backend.get("k1") == b"value1"
    await backend.delete("k1")
    assert await backend.get("k1") is None


@pytest.mark.asyncio
async def test_exists(backend: DiskCacheBackend) -> None:
    assert await backend.exists("k2") is False
    await backend.set("k2", b"v")
    assert await backend.exists("k2") is True


@pytest.mark.asyncio
async def test_delete_missing_is_noop(backend: DiskCacheBackend) -> None:
    await backend.delete("missing")


@pytest.mark.asyncio
async def test_delete_pattern_is_noop(backend: DiskCacheBackend) -> None:
    """Disk backend не поддерживает pattern delete (no-op без ошибок)."""
    await backend.set("a.b", b"1")
    await backend.delete_pattern("a.*")
    assert await backend.get("a.b") == b"1"
