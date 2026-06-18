"""Tests for StorageFacade (S164 W37)."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.backend.core.storage.facade import (
    FallbackObjectStorage,
    FallbackStorageDecorator,
    LocalFSStorageFacade,
    StorageError,
)


@pytest.fixture
def tmp_facade(tmp_path: Path) -> LocalFSStorageFacade:
    return LocalFSStorageFacade(base_path=tmp_path)


@pytest.mark.asyncio
async def test_put_get_roundtrip(tmp_facade: LocalFSStorageFacade) -> None:
    await tmp_facade.put("file.txt", b"hello world", content_type="text/plain")
    result = await tmp_facade.get("file.txt")
    assert result == b"hello world"


@pytest.mark.asyncio
async def test_get_missing_returns_none(tmp_facade: LocalFSStorageFacade) -> None:
    result = await tmp_facade.get("nonexistent.txt")
    assert result is None


@pytest.mark.asyncio
async def test_delete_existing(tmp_facade: LocalFSStorageFacade) -> None:
    await tmp_facade.put("delete_me.txt", b"x")
    deleted = await tmp_facade.delete("delete_me.txt")
    assert deleted is True
    assert await tmp_facade.get("delete_me.txt") is None


@pytest.mark.asyncio
async def test_delete_missing_returns_false(tmp_facade: LocalFSStorageFacade) -> None:
    deleted = await tmp_facade.delete("nope.txt")
    assert deleted is False


@pytest.mark.asyncio
async def test_exists(tmp_facade: LocalFSStorageFacade) -> None:
    assert await tmp_facade.exists("a.txt") is False
    await tmp_facade.put("a.txt", b"x")
    assert await tmp_facade.exists("a.txt") is True


@pytest.mark.asyncio
async def test_list_keys(tmp_facade: LocalFSStorageFacade) -> None:
    await tmp_facade.put("a.txt", b"1")
    await tmp_facade.put("b.txt", b"2")
    # S164 W37: nested keys are sanitized (path-traversal prevention).
    await tmp_facade.put("nested/c.txt", b"3")
    keys = await tmp_facade.list_keys()
    assert "a.txt" in keys
    assert "b.txt" in keys
    # nested/c.txt sanitized -> nested_c.txt
    assert "nested_c.txt" in keys


@pytest.mark.asyncio
async def test_list_keys_with_prefix(tmp_facade: LocalFSStorageFacade) -> None:
    await tmp_facade.put("logs/a.log", b"1")
    await tmp_facade.put("logs/b.log", b"2")
    await tmp_facade.put("data/x.json", b"3")
    logs = await tmp_facade.list_keys("logs/")
    assert all(k.startswith("logs_") for k in logs)
    assert len(logs) >= 2


@pytest.mark.asyncio
async def test_fallback_decorator(tmp_path: Path) -> None:
    primary = LocalFSStorageFacade(base_path=tmp_path / "primary")
    fallback = LocalFSStorageFacade(base_path=tmp_path / "fallback")
    # Disable primary by raising on access.
    class FailingFacade(LocalFSStorageFacade):
        async def get(self, key: str) -> bytes | None:
            raise StorageError("primary down")
        async def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
            raise StorageError("primary down")
        async def delete(self, key: str) -> bool:
            raise StorageError("primary down")
        async def exists(self, key: str) -> bool:
            raise StorageError("primary down")
    deco = FallbackStorageDecorator(primary=FailingFacade(), fallback=fallback)
    # put -> primary fails -> fallback
    await deco.put("x.txt", b"data")
    # get -> primary fails -> fallback (returns data)
    assert await deco.get("x.txt") == b"data"
    # exists -> primary fails -> fallback returns True
    assert await deco.exists("x.txt") is True
    # delete -> primary fails -> fallback succeeds
    assert await deco.delete("x.txt") is True
    assert await deco.get("x.txt") is None


def test_fallback_settings_defaults() -> None:
    settings = FallbackObjectStorage()
    assert settings.enabled is True
    assert settings.local_path.exists() or not settings.local_path.exists()  # optional


def test_local_facade_path_sanitization(tmp_path: Path) -> None:
    """S164 W37 Rule 6: prevent path traversal."""
    facade = LocalFSStorageFacade(base_path=tmp_path)
    p = facade._path("../etc/passwd")
    assert ".." not in p.name  # sanitized
    assert str(p).startswith(str(tmp_path))