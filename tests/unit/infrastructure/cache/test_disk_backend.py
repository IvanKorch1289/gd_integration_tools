"""Unit-тесты DiskCacheBackend (S133 W4)."""

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
async def test_delete_pattern_removes_matching_keys(backend: DiskCacheBackend) -> None:
    """Wave 18 (ADR-0391): pattern delete удаляет подходящие ключи.

    Раньше был no-op (ключи хэшируются SHA256) → disk-tier копил stale
    значения (дефект 8).
    """
    await backend.set("a.b", b"1")
    await backend.set("c.d", b"2")
    await backend.delete_pattern("a.*")
    assert await backend.get("a.b") is None
    assert await backend.get("c.d") == b"2"


@pytest.mark.asyncio
async def test_delete_by_pattern_returns_count(backend: DiskCacheBackend) -> None:
    """``delete_by_pattern`` возвращает число удалённых ключей."""
    await backend.set("a.b", b"1")
    await backend.set("a.c", b"2")
    await backend.set("c.d", b"3")
    assert await backend.delete_by_pattern("a.*") == 2
    assert await backend.get("c.d") == b"3"
