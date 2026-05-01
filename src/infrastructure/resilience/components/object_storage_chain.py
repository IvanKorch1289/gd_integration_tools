"""Wiring W26.4: MinIO/S3 → LocalFS (Wave F.5a/b: contract fix + factory).

Контракт callable: ``async def storage_get(key: str) -> bytes``.

Only-read операция. Write идёт в primary; LocalFS-fallback хранит
кэш-копии прочитанных файлов (best-effort).

Wave F.5a: ранее использовались устаревшие имена ``LocalFsObjectStorage``
и метод ``.get()`` — реальный ABC :class:`ObjectStorage` определяет
``download()``, а реализация называется :class:`LocalFSStorage`. Это
делало chain неработающим. Сейчас всё идёт через
:func:`infrastructure.storage.factory.get_object_storage` /
:func:`get_local_fs_storage`.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

__all__ = (
    "StorageGetCallable",
    "build_object_storage_fallbacks",
    "build_object_storage_primary",
)

logger = logging.getLogger(__name__)

StorageGetCallable = Callable[[str], Awaitable[bytes]]


async def _primary_get(key: str) -> bytes:
    """Чтение через primary backend (S3/MinIO либо LocalFS-fallback)."""
    from src.infrastructure.storage.factory import get_object_storage

    backend = get_object_storage()
    return await backend.download(key)


async def _local_fs_get(key: str) -> bytes:
    """Чтение через LocalFS-fallback (W26.4)."""
    from src.infrastructure.storage.factory import get_local_fs_storage

    backend = get_local_fs_storage()
    return await backend.download(key)


def build_object_storage_primary() -> StorageGetCallable:
    return _primary_get


def build_object_storage_fallbacks() -> dict[str, StorageGetCallable]:
    return {"local_fs": _local_fs_get}
