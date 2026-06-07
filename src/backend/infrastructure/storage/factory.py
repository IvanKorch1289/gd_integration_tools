"""Factory + S3→LocalFS fallback chain для :class:`ObjectStorage` (S61 W1).

Унифицированный способ получить ``ObjectStorage`` instance:

* :func:`get_object_storage` — primary backend по
  ``settings.storage.provider``: ``"local"`` → LocalFS, любой другой
  (``"s3"`` / ``"minio"`` / ``"aws"``) → :class:`S3ObjectStorage` поверх
  aioboto3 (Wave 2.4 закрыт, S61 W1). При недоступности S3 — fallback
  на LocalFS с warning, чтобы dev_light не падал без aioboto3.
* :func:`get_local_fs_storage` — singleton LocalFS-backend
  (``var/storage`` по умолчанию или ``settings.storage.local_storage_path``).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from src.backend.core.interfaces.storage import ObjectStorage
from src.backend.infrastructure.logging.factory import get_logger

__all__ = ("get_local_fs_storage", "get_object_storage")

logger = get_logger(__name__)


@lru_cache(maxsize=1)
def get_local_fs_storage() -> ObjectStorage:
    """LocalFS-backend singleton.

    Путь берётся из ``settings.storage.local_storage_path`` если задан;
    иначе — ``var/storage``.
    """
    from src.backend.infrastructure.storage.local_fs import LocalFSStorage

    base_path: Path
    try:
        from src.backend.core.config.settings import settings

        configured = getattr(settings.storage, "local_storage_path", None)
        base_path = Path(configured) if configured else Path("var/storage")
    except Exception as _:
        base_path = Path("var/storage")
    return LocalFSStorage(base_path=base_path)


@lru_cache(maxsize=1)
def get_object_storage() -> ObjectStorage:
    """Возвращает primary ``ObjectStorage`` по ``settings.storage.provider``.

    * ``"local"`` → :class:`LocalFSStorage`.
    * любой другой (``"s3"`` / ``"minio"`` / ``"aws"``) →
      :class:`S3ObjectStorage` поверх aioboto3. При отсутствии aioboto3
      или ошибке инициализации — fallback на LocalFS с warning
      (чтобы dev_light не падал на свежей инсталляции без [sources-cdc]).
    """
    try:
        from src.backend.core.config.settings import settings

        provider = (getattr(settings.storage, "provider", "local") or "local").lower()
    except Exception as _:
        provider = "local"

    if provider == "local":
        return get_local_fs_storage()

    try:
        from src.backend.core.config.services.storage import fs_settings
        from src.backend.infrastructure.storage.s3 import S3ObjectStorage

        return S3ObjectStorage(fs_settings)
    except ImportError as exc:
        logger.warning(
            "ObjectStorage provider=%r требует aioboto3 (S61 W1, install "
            "[sources-cdc]); fallback на LocalFS. cause=%s",
            provider,
            exc,
        )
        return get_local_fs_storage()
    except Exception as exc:
        logger.warning(
            "S3ObjectStorage init failed provider=%r; fallback на LocalFS. cause=%s",
            provider,
            exc,
        )
        return get_local_fs_storage()
