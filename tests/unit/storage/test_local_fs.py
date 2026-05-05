"""Unit-тесты ``LocalFSStorage`` через ``tmp_path``.

Покрывает:

* round-trip ``upload`` -> ``download`` для байтов;
* ``delete(key)`` после ``exists(key)=True`` -> ``exists(key)=False``;
* ``list_keys(prefix)`` после нескольких uploads (поддержка вложенных
  префиксов и сортировка результата);
* ``presigned_url(key)`` возвращает корректный ``file://`` URI;
* отсев path-traversal ключей (``..``/абсолютные пути) -> ``ValueError``.

Тесты не используют сеть и реальный S3 — только локальная FS из
``pytest tmp_path``.
"""

# ruff: noqa: S101  # assert — стандартная идиома pytest

from __future__ import annotations

from pathlib import Path

import pytest

from src.backend.infrastructure.storage.local_fs import LocalFSStorage


@pytest.fixture
def storage(tmp_path: Path) -> LocalFSStorage:
    """Возвращает ``LocalFSStorage`` поверх изолированной ``tmp_path``."""
    return LocalFSStorage(base_path=tmp_path)


async def test_upload_download_roundtrip(storage: LocalFSStorage) -> None:
    """``upload`` сохраняет байты, ``download`` возвращает их без изменений."""
    payload = b"hello world\n"
    await storage.upload("docs/note.txt", payload)
    assert await storage.download("docs/note.txt") == payload


async def test_upload_overwrites_existing(storage: LocalFSStorage) -> None:
    """Повторный ``upload`` под тем же ключом перезаписывает данные атомарно."""
    await storage.upload("a.bin", b"v1")
    await storage.upload("a.bin", b"v2-longer")
    assert await storage.download("a.bin") == b"v2-longer"


async def test_delete_removes_existing_key(storage: LocalFSStorage) -> None:
    """После ``delete`` файл больше не существует, ``exists`` возвращает False."""
    await storage.upload("tmp/x.bin", b"data")
    assert await storage.exists("tmp/x.bin") is True

    await storage.delete("tmp/x.bin")
    assert await storage.exists("tmp/x.bin") is False


async def test_delete_missing_key_is_noop(storage: LocalFSStorage) -> None:
    """``delete`` несуществующего ключа не падает (идемпотентно)."""
    await storage.delete("never-was-here.bin")
    assert await storage.exists("never-was-here.bin") is False


async def test_list_keys_returns_relative_sorted_paths(
    storage: LocalFSStorage,
) -> None:
    """После нескольких uploads ``list_keys`` возвращает относительные пути."""
    await storage.upload("a.bin", b"1")
    await storage.upload("dir/b.bin", b"2")
    await storage.upload("dir/sub/c.bin", b"3")

    keys = await storage.list_keys()
    assert keys == ["a.bin", "dir/b.bin", "dir/sub/c.bin"]


async def test_list_keys_with_prefix(storage: LocalFSStorage) -> None:
    """``list_keys(prefix)`` фильтрует только записи внутри префикса."""
    await storage.upload("a.bin", b"1")
    await storage.upload("dir/b.bin", b"2")
    await storage.upload("dir/sub/c.bin", b"3")

    keys = await storage.list_keys("dir")
    assert keys == ["dir/b.bin", "dir/sub/c.bin"]


async def test_list_keys_missing_prefix_returns_empty(
    storage: LocalFSStorage,
) -> None:
    """Несуществующий префикс возвращает пустой список без ошибки."""
    assert await storage.list_keys("no-such-prefix") == []


async def test_presigned_url_returns_file_uri(
    storage: LocalFSStorage, tmp_path: Path
) -> None:
    """``presigned_url`` возвращает ``file://`` URI на абсолютный путь."""
    await storage.upload("a.txt", b"x")
    url = await storage.presigned_url("a.txt")
    assert url.startswith("file://")
    # URL должен указывать ровно на загруженный файл
    expected = (tmp_path / "a.txt").resolve().as_uri()
    assert url == expected


async def test_unsafe_key_path_traversal_rejected(
    storage: LocalFSStorage,
) -> None:
    """Ключ с ``..`` отвергается как path-traversal."""
    with pytest.raises(ValueError):
        await storage.upload("../escape.bin", b"x")


async def test_unsafe_key_absolute_rejected(storage: LocalFSStorage) -> None:
    """Абсолютный ключ (начинается с ``/``) отвергается."""
    with pytest.raises(ValueError):
        await storage.upload("/etc/passwd", b"x")


async def test_unsafe_key_empty_rejected(storage: LocalFSStorage) -> None:
    """Пустой ключ отвергается."""
    with pytest.raises(ValueError):
        await storage.exists("")
