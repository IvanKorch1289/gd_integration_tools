"""Focused tests DiskTTLCache (pickle-free замена diskcache, PYSEC-2026-2447).

2026-09-11: DiskTTLCache переведён с diskcache.Cache (pickle, CVE без фикса)
на собственный _IndexedByteStore: значения — bytes-файлы (sha256-шардирование),
индекс ключей — JSON. TTL живёт на envelope.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.backend.infrastructure.decorators.caching.storage.disk import DiskTTLCache


@pytest.fixture
def cache(tmp_path: Path) -> DiskTTLCache:
    """DiskTTLCache с временной директорией."""
    return DiskTTLCache(directory=tmp_path)


@pytest.mark.asyncio
async def test_set_get_roundtrip(cache: DiskTTLCache) -> None:
    """set() + get() → envelope с исходным value."""
    await cache.set("k1", {"a": 1}, ttl_seconds=60)
    envelope = await cache.get("k1")
    assert envelope is not None
    assert envelope.is_alive()
    assert envelope.value == {"a": 1}


@pytest.mark.asyncio
async def test_get_missing_returns_none(cache: DiskTTLCache) -> None:
    """get() несуществующего ключа → None."""
    assert await cache.get("never") is None


@pytest.mark.asyncio
async def test_ttl_expiry(cache: DiskTTLCache) -> None:
    """Протухший envelope (fresh_until в прошлом) → get() = None, файл удалён.

    ttl_seconds=0 в контракте envelope означает «без TTL» (как и в
    diskcache-версии), поэтому expiry проверяем прямым payload.
    """

    from src.backend.infrastructure.decorators.caching.envelope import CacheEnvelope

    expired = CacheEnvelope.create(value="v", ttl_seconds=60)
    # fresh_until/stale_until — time.monotonic() float'ы: 0.0 = «давно истёк».
    expired.fresh_until = 0.0
    expired.stale_until = 0.0
    cache._store.set("exp", cache._serialize_envelope(expired))

    assert await cache.get("exp") is None
    assert await cache.get("exp") is None  # повторно — тоже miss (файл удалён)


@pytest.mark.asyncio
async def test_delete(cache: DiskTTLCache) -> None:
    """delete() удаляет запись."""
    await cache.set("k", "v", ttl_seconds=60)
    await cache.delete("k")
    assert await cache.get("k") is None


@pytest.mark.asyncio
async def test_delete_pattern(cache: DiskTTLCache) -> None:
    """delete_pattern() удаляет по fnmatch (через индекс ключей)."""
    await cache.set("prefix_a", "1", ttl_seconds=60)
    await cache.set("prefix_b", "2", ttl_seconds=60)
    await cache.set("other", "3", ttl_seconds=60)
    await cache.delete_pattern("prefix_*")
    assert await cache.get("prefix_a") is None
    assert await cache.get("prefix_b") is None
    assert (await cache.get("other")).value == "3"  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_index_survives_reopen(tmp_path: Path) -> None:
    """Индекс персистентен: новый инстанс видит записи старого."""
    first = DiskTTLCache(directory=tmp_path)
    await first.set("persist", "v", ttl_seconds=60)
    await first.close()

    second = DiskTTLCache(directory=tmp_path)
    envelope = await second.get("persist")
    assert envelope is not None and envelope.value == "v"


@pytest.mark.asyncio
async def test_no_pickle_payload(cache: DiskTTLCache, tmp_path: Path) -> None:
    """На диске нет pickle-байтов: payload — JSON envelope (PYSEC-2026-2447)."""
    await cache.set("safe", {"x": 1}, ttl_seconds=60)
    files = [p for p in tmp_path.rglob("*") if p.is_file() and p.name != "index.json"]
    assert files, "ожидался хотя бы один файл значения"
    for f in files:
        head = f.read_bytes()[:1]
        assert head in (b"{", b"["), f"не-JSON payload в {f}"


@pytest.mark.asyncio
async def test_dir_created_with_private_mode(tmp_path: Path) -> None:
    """Каталог создаётся с 0o700 (defence-in-depth PYSEC-2026-2447)."""
    target = tmp_path / "nested" / "cache"
    DiskTTLCache(directory=target)
    assert (target.stat().st_mode & 0o777) == 0o700
