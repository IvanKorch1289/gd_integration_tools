"""Factory + S3→LocalFS fallback chain для :class:`ObjectStorage` (Wave F.5a/b).

Унифицированный способ получить ``ObjectStorage`` instance:

* :func:`get_object_storage` — primary backend по
  ``settings.storage.provider`` (``"local"`` → LocalFS, иначе → пытается
  поднять S3-обёртку; при недоступности — fallback на LocalFS с warning,
  чтобы dev_light не падал на свежей инсталляции без aiobotocore).
* :func:`get_local_fs_storage` — singleton LocalFS-backend
  (``var/storage`` по умолчанию или ``settings.storage.local_storage_path``).

Дальнейшие шаги (Wave 2.4): реальная S3-обёртка ``S3ObjectStorage``
поверх ``S3Client`` с retry/CB; интеграция с :class:`ResilienceCoordinator`.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

from src.core.interfaces.storage import ObjectStorage

__all__ = ("get_object_storage", "get_local_fs_storage")

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_local_fs_storage() -> ObjectStorage:
    """LocalFS-backend singleton.

    Путь берётся из ``settings.storage.local_storage_path`` если задан;
    иначе — ``var/storage``.
    """
    from src.infrastructure.storage.local_fs import LocalFSStorage

    base_path: Path
    try:
        from src.core.config.settings import settings

        configured = getattr(settings.storage, "local_storage_path", None)
        base_path = Path(configured) if configured else Path("var/storage")
    except Exception:  # noqa: BLE001
        base_path = Path("var/storage")
    return LocalFSStorage(base_path=base_path)


@lru_cache(maxsize=1)
def get_object_storage() -> ObjectStorage:
    """Возвращает primary ``ObjectStorage`` по ``settings.storage.provider``.

    * ``"local"`` → LocalFS.
    * любой другой (``"s3"`` / ``"minio"`` / ...) — попытка поднять
      S3-обёртку. Полноценная реализация придёт в Wave 2.4; до того при
      ``provider != "local"`` возвращаем LocalFS с предупреждением.
    """
    try:
        from src.core.config.settings import settings

        provider = (getattr(settings.storage, "provider", "local") or "local").lower()
    except Exception:  # noqa: BLE001
        provider = "local"

    if provider == "local":
        return get_local_fs_storage()

    # Wave 2.4 — здесь будет реальный S3ObjectStorage поверх S3Client.
    logger.warning(
        "ObjectStorage provider=%r — полноценная реализация ждёт Wave 2.4; "
        "временно используется LocalFS fallback (var/storage). "
        "Для prod установите [sources-cdc] и реализуйте S3ObjectStorage.",
        provider,
    )
    return get_local_fs_storage()
