"""Wiring W26.4: MinIO/S3 → LocalFS.

Контракт callable: ``async def storage_get(key: str) -> bytes``.

Only-read операция. Write идёт в primary; LocalFS-fallback хранит
кэш-копии прочитанных файлов (best-effort).
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


async def _minio_get(key: str) -> bytes:
    from src.infrastructure.storage.factory import get_object_storage

    backend = get_object_storage()  # primary через factory (S3/MinIO)
    return await backend.get(key)


async def _local_fs_get(key: str) -> bytes:
    from src.infrastructure.storage.local_fs import LocalFsObjectStorage

    backend: LocalFsObjectStorage = _local_fs_singleton()
    return await backend.get(key)


_local_fs_backend = None


def _local_fs_singleton():
    global _local_fs_backend
    if _local_fs_backend is None:
        from pathlib import Path

        from src.infrastructure.storage.local_fs import LocalFsObjectStorage

        _local_fs_backend = LocalFsObjectStorage(base_path=Path("var/storage"))
    return _local_fs_backend


def build_object_storage_primary() -> StorageGetCallable:
    return _minio_get


def build_object_storage_fallbacks() -> dict[str, StorageGetCallable]:
    return {"local_fs": _local_fs_get}
