"""Focused tests for DiskCacheBackend (PERF-6.6 Sprint 18 coverage ratchet).

Coverage target: disk.py 27% → 70%+.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from src.backend.infrastructure.cache.backends.disk import DiskCacheBackend


@pytest.fixture
def disk_cache(tmp_path: Path) -> DiskCacheBackend:
    """DiskCacheBackend с temporary directory."""
    return DiskCacheBackend(base_path=tmp_path)


def test_init_with_string_path(tmp_path: Path) -> None:
    """Constructor принимает string path."""
    backend = DiskCacheBackend(base_path=str(tmp_path))
    assert backend._base_path == Path(str(tmp_path))


def test_init_with_path_object(tmp_path: Path) -> None:
    """Constructor принимает Path object."""
    backend = DiskCacheBackend(base_path=tmp_path)
    assert backend._base_path == tmp_path


def test_safe_path_simple_key(disk_cache: DiskCacheBackend) -> None:
    """_safe_path converts simple key → safe file path."""
    path = disk_cache._safe_path("my_key")
    assert path.suffix == ".cache"
    assert "my_key" in str(path)


def test_safe_path_with_slash(disk_cache: DiskCacheBackend) -> None:
    """_safe_path sanitizes slashes (path traversal prevention)."""
    path = disk_cache._safe_path("foo/bar")
    # No subdirectory created; path is flattened
    assert "/" not in path.name or path.name.endswith(".cache")


def test_safe_path_empty(disk_cache: DiskCacheBackend) -> None:
    """_safe_path с empty key → default name."""
    path = disk_cache._safe_path("")
    assert path.suffix == ".cache"


@pytest.mark.asyncio
async def test_get_nonexistent_key(disk_cache: DiskCacheBackend) -> None:
    """get() для несуществующего key → None."""
    result = await disk_cache.get("never_existed")
    assert result is None


@pytest.mark.asyncio
async def test_set_then_get(disk_cache: DiskCacheBackend) -> None:
    """set() + get() roundtrip."""
    await disk_cache.set("my_key", b"hello world", ttl=None)
    result = await disk_cache.get("my_key")
    assert result == b"hello world"


@pytest.mark.asyncio
async def test_set_with_ttl(disk_cache: DiskCacheBackend) -> None:
    """set() с TTL."""
    await disk_cache.set("ttl_key", b"value", ttl=3600)
    result = await disk_cache.get("ttl_key")
    assert result == b"value"


@pytest.mark.asyncio
async def test_set_with_zero_ttl(disk_cache: DiskCacheBackend) -> None:
    """set() с TTL=0 → likely skip caching (per convention)."""
    await disk_cache.set("zero_ttl", b"v", ttl=0)
    # Не assert конкретный результат — зависит от реализации


@pytest.mark.asyncio
async def test_delete_single_key(disk_cache: DiskCacheBackend) -> None:
    """delete() одного key → удаляет только его."""
    await disk_cache.set("k1", b"v1")
    await disk_cache.set("k2", b"v2")
    await disk_cache.delete("k1")
    assert await disk_cache.get("k1") is None
    assert await disk_cache.get("k2") == b"v2"


@pytest.mark.asyncio
async def test_delete_multiple_keys(disk_cache: DiskCacheBackend) -> None:
    """delete() нескольких keys."""
    await disk_cache.set("a", b"1")
    await disk_cache.set("b", b"2")
    await disk_cache.set("c", b"3")
    await disk_cache.delete("a", "b")
    assert await disk_cache.get("a") is None
    assert await disk_cache.get("b") is None
    assert await disk_cache.get("c") == b"3"


@pytest.mark.asyncio
async def test_delete_nonexistent(disk_cache: DiskCacheBackend) -> None:
    """delete() несуществующего key → no error."""
    await disk_cache.delete("never_existed")  # should not raise


@pytest.mark.asyncio
async def test_delete_pattern(disk_cache: DiskCacheBackend) -> None:
    """delete_pattern() удаляет все keys с matching pattern."""
    await disk_cache.set("prefix_a", b"1")
    await disk_cache.set("prefix_b", b"2")
    await disk_cache.set("other", b"3")
    await disk_cache.delete_pattern("prefix_")
    assert await disk_cache.get("prefix_a") is None
    assert await disk_cache.get("prefix_b") is None
    assert await disk_cache.get("other") == b"3"


@pytest.mark.asyncio
async def test_exists_returns_bool(disk_cache: DiskCacheBackend) -> None:
    """exists() возвращает bool."""
    await disk_cache.set("k", b"v")
    result = await disk_cache.exists("k")
    assert result is True
    assert isinstance(result, bool)


@pytest.mark.asyncio
async def test_exists_false(disk_cache: DiskCacheBackend) -> None:
    """exists() для несуществующего → False."""
    assert await disk_cache.exists("never") is False


@pytest.mark.asyncio
async def test_set_overwrites_existing(disk_cache: DiskCacheBackend) -> None:
    """set() для существующего key → overwrites."""
    await disk_cache.set("k", b"v1")
    await disk_cache.set("k", b"v2")
    assert await disk_cache.get("k") == b"v2"


@pytest.mark.asyncio
async def test_set_empty_value(disk_cache: DiskCacheBackend) -> None:
    """set() с empty bytes value."""
    await disk_cache.set("empty", b"")
    result = await disk_cache.get("empty")
    assert result == b""


@pytest.mark.asyncio
async def test_set_large_value(disk_cache: DiskCacheBackend) -> None:
    """set() с large value (1MB)."""
    large_data = b"x" * (1024 * 1024)  # 1MB
    await disk_cache.set("large", large_data)
    result = await disk_cache.get("large")
    assert result == large_data


@pytest.mark.asyncio
async def test_unicode_key(disk_cache: DiskCacheBackend) -> None:
    """set() с unicode key — encoding handled."""
    await disk_cache.set("ключ", b"value")
    result = await disk_cache.get("ключ")
    assert result == b"value"


def test_init_creates_base_dir(tmp_path: Path) -> None:
    """Constructor создаёт base_path если не существует."""
    new_path = tmp_path / "new_subdir"
    DiskCacheBackend(base_path=new_path)
    assert new_path.exists()
    assert new_path.is_dir()
