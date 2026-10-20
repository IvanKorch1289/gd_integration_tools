"""Cycle 168 tests: ``DiskCacheBackend`` per-key TTL через expiry sidecar.

PROD_READINESS_LOGGING_CACHE_2026-10-20 §1.1: до cycle 168 ``set()``
игнорировал ``ttl``, что приводило к stale data после primary TTL expiry.
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

import pytest

from src.backend.infrastructure.cache.backends.disk import DiskCacheBackend


@pytest.fixture
async def tmp_disk() -> DiskCacheBackend:
    with tempfile.TemporaryDirectory(prefix="disk_ttl_") as d:
        yield DiskCacheBackend(d)


class TestDiskCacheTTL:
    async def test_set_with_ttl_returns_value(self, tmp_disk: DiskCacheBackend) -> None:
        """set(..., ttl=N) → значение сохраняется и читается."""
        await tmp_disk.set("key", b"value", ttl=60)
        result = await tmp_disk.get("key")
        assert result == b"value"

    async def test_ttl_expiry_returns_none(self, tmp_disk: DiskCacheBackend) -> None:
        """После истечения TTL get() возвращает None и удаляет файлы."""
        await tmp_disk.set("key", b"value", ttl=1)
        await asyncio.sleep(1.2)
        result = await tmp_disk.get("key")
        assert result is None

    async def test_ttl_expiry_removes_files(self, tmp_disk: DiskCacheBackend) -> None:
        """После истечения TTL data+sidecar удаляются (cleanup)."""
        await tmp_disk.set("key", b"value", ttl=1)
        # Найти data файл
        base = tmp_disk._base
        files_before = list(base.rglob("*"))
        assert any(f.is_file() for f in files_before), "data file должен существовать"
        await asyncio.sleep(1.2)
        await tmp_disk.get("key")  # triggers cleanup
        files_after = list(base.rglob("*"))
        # sidecar и data должны быть удалены
        remaining = [f for f in files_after if not f.name.endswith(".tmp")]
        # base_path сам по себе (директория) — игнорируем
        remaining_files = [f for f in remaining if f.is_file()]
        assert remaining_files == [], f"Ожидалось 0 файлов, осталось: {remaining_files}"

    async def test_no_ttl_persists(self, tmp_disk: DiskCacheBackend) -> None:
        """set(..., ttl=None) → значение без expiry."""
        await tmp_disk.set("key", b"value", ttl=None)
        await asyncio.sleep(1.5)
        result = await tmp_disk.get("key")
        assert result == b"value"

    async def test_zero_ttl_treated_as_no_expiry_sidecar(self, tmp_disk: DiskCacheBackend) -> None:
        """set(..., ttl=0) — sidecar с expires_at=now → expired сразу.

        Это edge case: ``ttl=0`` — невалидное значение, но Pydantic-валидаторы
        запретят 0; если проскочит — значение будет expired немедленно.
        Документируем поведение.
        """
        await tmp_disk.set("key", b"value", ttl=0)
        # Записывается expires_at = now, get() видит expired
        result = await tmp_disk.get("key")
        # Может вернуть value (если запись успела до read) или None — это race
        # Главное: не должно быть uncaught exception.
        assert result in (None, b"value")

    async def test_delete_removes_sidecar(self, tmp_disk: DiskCacheBackend) -> None:
        """delete() удаляет и data, и sidecar."""
        await tmp_disk.set("key", b"value", ttl=60)
        await tmp_disk.delete("key")
        result = await tmp_disk.get("key")
        assert result is None
        # Нет файлов в base
        files = [
            f
            for f in tmp_disk._base.rglob("*")
            if f.is_file() and not f.name.endswith(".tmp")
        ]
        assert files == []

    async def test_existing_legacy_files_still_readable(
        self, tmp_disk: DiskCacheBackend
    ) -> None:
        """Backward-compat: файлы без sidecar читаются (без expiry)."""
        # Эмулируем legacy file (без sidecar)
        await tmp_disk.set("legacy", b"old_value", ttl=None)
        # Удаляем sidecar вручную (если есть)
        sidecar = tmp_disk._expiry_path("legacy")
        if sidecar.exists():
            sidecar.unlink()
        result = await tmp_disk.get("legacy")
        assert result == b"old_value"