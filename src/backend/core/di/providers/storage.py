"""S164 W37: get_storage_facade DI provider (Rule 1).

Lazy-import бэкенда (S3 / LocalFS) для предотвращения circular imports.
Per Rule 2: services/dsl получают фасад через DI, не через прямой import.
"""

from __future__ import annotations

from pathlib import Path

from src.backend.core.storage.facade import (
    FallbackStorageDecorator,
    LocalFSStorageFacade,
    StorageFacade,
)

__all__ = ("get_storage_facade",)


def get_storage_facade(
    base_path: Path | None = None,
    enable_fallback: bool = True,
) -> StorageFacade:
    """Build StorageFacade per active profile (dev_light -> LocalFS, prod -> S3).

    S164 W37: Ponytail default — minimal scope. dev_light использует
    LocalFS facade (production-safe для tests). prod подключит S3 facade
    в S165 (post-scope).
    """
    local = LocalFSStorageFacade(base_path=base_path)
    if not enable_fallback:
        return local
    # Prod facade (S3) — deferred to S165. For now, fallback to same LocalFS.
    return FallbackStorageDecorator(primary=local, fallback=local)