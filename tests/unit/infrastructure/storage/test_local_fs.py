"""Unit-tests for LocalFSStorage backend."""

from __future__ import annotations

import os
import warnings
from pathlib import Path
from unittest.mock import AsyncMock, patch

import aiofiles
import pytest

from src.backend.infrastructure.storage.local_fs import LocalFSStorage


@pytest.fixture
def storage(tmp_path: Path) -> LocalFSStorage:
    return LocalFSStorage(base_path=tmp_path)


def test_init_creates_base_path(tmp_path: Path) -> None:
    base = tmp_path / "new_dir"
    LocalFSStorage(base_path=base)
    assert base.exists()


def test_init_warns_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENVIRONMENT", "production")
    with pytest.warns(RuntimeWarning, match="небезопасно"):
        LocalFSStorage(base_path="/tmp/test_local_fs_prod")


def test_safe_path_valid(storage: LocalFSStorage, tmp_path: Path) -> None:
    path = storage._safe_path("foo/bar.txt")
    assert path == (tmp_path / "foo" / "bar.txt").resolve()


def test_safe_path_rejects_empty(storage: LocalFSStorage) -> None:
    with pytest.raises(ValueError, match="Небезопасный ключ"):
        storage._safe_path("")


def test_safe_path_rejects_absolute(storage: LocalFSStorage) -> None:
    with pytest.raises(ValueError, match="Небезопасный ключ"):
        storage._safe_path("/etc/passwd")


def test_safe_path_rejects_traversal(storage: LocalFSStorage) -> None:
    with pytest.raises(ValueError, match="Небезопасный ключ"):
        storage._safe_path("foo/../../etc/passwd")


def test_safe_path_rejects_escape(storage: LocalFSStorage) -> None:
    with pytest.raises(ValueError, match="Ключ выходит за пределы"):
        storage._safe_path("../secret.txt")


@pytest.mark.asyncio
async def test_upload_and_download(storage: LocalFSStorage, tmp_path: Path) -> None:
    data = b"hello world"
    path = await storage.upload("test/key.bin", data)
    assert Path(path).exists()
    downloaded = await storage.download("test/key.bin")
    assert downloaded == data


@pytest.mark.asyncio
async def test_delete_existing(storage: LocalFSStorage) -> None:
    await storage.upload("del/me.txt", b"data")
    assert await storage.exists("del/me.txt")
    await storage.delete("del/me.txt")
    assert not await storage.exists("del/me.txt")


@pytest.mark.asyncio
async def test_delete_missing_no_error(storage: LocalFSStorage) -> None:
    await storage.delete("missing/file.txt")


@pytest.mark.asyncio
async def test_exists_false(storage: LocalFSStorage) -> None:
    assert not await storage.exists("nonexistent")


@pytest.mark.asyncio
async def test_list_keys(storage: LocalFSStorage, tmp_path: Path) -> None:
    await storage.upload("a/1.txt", b"1")
    await storage.upload("a/2.txt", b"2")
    await storage.upload("b/3.txt", b"3")
    keys = await storage.list_keys("")
    assert keys == ["a/1.txt", "a/2.txt", "b/3.txt"]


@pytest.mark.asyncio
async def test_list_keys_with_prefix(storage: LocalFSStorage) -> None:
    await storage.upload("a/1.txt", b"1")
    await storage.upload("b/3.txt", b"3")
    keys = await storage.list_keys("a")
    assert keys == ["a/1.txt"]


@pytest.mark.asyncio
async def test_list_keys_missing_prefix(storage: LocalFSStorage) -> None:
    assert await storage.list_keys("z") == []


@pytest.mark.asyncio
async def test_list_keys_single_file(storage: LocalFSStorage) -> None:
    await storage.upload("single.txt", b"x")
    keys = await storage.list_keys("single.txt")
    assert keys == ["single.txt"]


@pytest.mark.asyncio
async def test_list_keys_skips_tmp(storage: LocalFSStorage, tmp_path: Path) -> None:
    await storage.upload("keep.txt", b"x")
    # simulate tmp file in base
    (tmp_path / "ignore.tmp").write_text("tmp")
    keys = await storage.list_keys("")
    assert keys == ["keep.txt"]


@pytest.mark.asyncio
async def test_presigned_url(storage: LocalFSStorage) -> None:
    await storage.upload("doc.pdf", b"pdf")
    url = await storage.presigned_url("doc.pdf")
    assert url.startswith("file://")
    assert "doc.pdf" in url
