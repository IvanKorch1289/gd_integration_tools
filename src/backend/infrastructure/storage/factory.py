"""Factory + S3→LocalFS fallback chain для :class:`ObjectStorage` (S61 W1, S131 W1).

Унифицированный способ получить ``ObjectStorage`` instance:

* :func:`get_object_storage` — primary backend по
  ``settings.storage.provider``: ``"local"`` → LocalFS, любой другой
  (``"s3"`` / ``"minio"`` / ``"aws"``) → :class:`S3ObjectStorage` поверх
  aioboto3 (Wave 2.4 закрыт, S61 W1), wrapped в
  :class:`FallbackObjectStorage` (S130 W3, S131 W1) с LocalFS-secondary
  для runtime try-S3-then-fallback. ``config_profiles/base.yml`` уже
  содержит ``resilience.fallbacks.minio: {chain: ["local_fs"], mode: auto}``
  (W26) — runtime chain теперь согласован с config. При недоступности
  S3 init — bare LocalFS с warning, чтобы dev_light не падал без aioboto3.
* :func:`get_local_fs_storage` — singleton LocalFS-backend
  (``var/storage`` по умолчанию или ``settings.storage.local_storage_path``).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from src.backend.core.interfaces.storage import ObjectStorage
from src.backend.core.logging import get_logger

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
    """Возвращает ``ObjectStorage`` по ``settings.storage.provider``.

    * ``"local"`` → :class:`LocalFSStorage` (bare, без wrapper).
    * любой другой (``"s3"`` / ``"minio"`` / ``"aws"``) →
      :class:`S3ObjectStorage` поверх aioboto3, **wrapped в
      :class:`FallbackObjectStorage` с LocalFS secondary** (S131 W1).
      Runtime try-S3-then-fallback per
      ``resilience.fallbacks.minio: {chain: ["local_fs"]}`` (W26).
      При отсутствии aioboto3 или ошибке инициализации — fallback
      на bare LocalFS с warning (чтобы dev_light не падал на свежей
      инсталляции без [sources-cdc]).

    Singleton via ``lru_cache`` — wrapper переиспользуется между вызовами.
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

        primary = S3ObjectStorage(fs_settings)
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

    # S131 W1: wrap S3 → FallbackObjectStorage с LocalFS secondary.
    # Runtime try-S3-then-fallback согласован с
    # resilience.fallbacks.minio: {chain: ["local_fs"]} (W26).
    from src.backend.infrastructure.storage.fallback import FallbackObjectStorage

    logger.info(
        "ObjectStorage provider=%r → FallbackObjectStorage(S3 → LocalFS) per "
        "resilience.fallbacks.minio chain",
        provider,
    )
    return FallbackObjectStorage(
        primary=primary,
        secondary=get_local_fs_storage(),
        name=f"storage.{provider}→local_fs",
    )
