"""Wave 18 (ADR-0391): pattern-delete чистит и disk-tier.

Дефект 8 (low): ``UnifiedCacheFacade.delete_pattern_ns`` чистил только
primary + memory. Disk-tier (L3) оставался со stale-значениями → после
падения Redis клиент получал устаревшие данные из диска.

``DiskCacheBackend.delete_pattern`` был no-op (ключи хэшируются SHA256,
из файла имя ключа не восстановить). Теперь backend держит in-memory
индекс записанных ключей и удаляет их по glob-паттерну.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.backend.infrastructure.cache.backends.disk import DiskCacheBackend
from src.backend.infrastructure.cache.backends.memory import MemoryBackend
from src.backend.services.cache.facade import UnifiedCacheFacade


@pytest.fixture()
def disk(tmp_path: Path) -> DiskCacheBackend:
    """Disk-backend во временном каталоге."""
    return DiskCacheBackend(tmp_path / "disk")


@pytest.mark.asyncio
async def test_disk_delete_pattern_removes_matching_keys(
    disk: DiskCacheBackend,
) -> None:
    """Pattern-delete удаляет подходящие ключи и оставляет остальные."""
    await disk.set("ns:a", b"1")
    await disk.set("ns:b", b"2")
    await disk.set("other", b"3")

    await disk.delete_pattern("ns:*")

    assert await disk.get("ns:a") is None
    assert await disk.get("ns:b") is None
    assert await disk.get("other") == b"3"


@pytest.mark.asyncio
async def test_facade_delete_pattern_ns_clears_disk_tier(
    tmp_path: Path,
) -> None:
    """delete_pattern_ns чистит disk-tier (иначе stale при падении Redis)."""
    facade = UnifiedCacheFacade(
        primary=MemoryBackend(maxsize=10),
        memory_fallback=MemoryBackend(maxsize=10),
        disk_fallback=DiskCacheBackend(tmp_path / "disk"),
    )

    await facade.set_ns("ns.a", b"1", namespace="ns")
    await facade.set_ns("ns.b", b"2", namespace="ns")
    await facade.set_ns("other", b"3", namespace="ns")

    await facade.delete_pattern_ns("ns.*", namespace="ns")

    # Ни primary, ни memory, ни disk не должны держать удалённые ключи.
    assert (await facade.get_ns("ns.a", namespace="ns")).hit is False
    assert (await facade.get_ns("ns.b", namespace="ns")).hit is False
    assert (await facade.get_ns("other", namespace="ns")).value == b"3"
