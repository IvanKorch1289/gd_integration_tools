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

**Composition root fail-stop (Sprint 3.2)**: factory.py — единственная
точка входа storage из lifespan'а (``composition.service_setup.register_all_services``).
При ``settings.app.environment == "production"`` и попытке инстанциировать
LocalFS (прямо или через fallback) поднимается
:class:`core.config.validator.ProductionConfigError` ещё до того, как
первый storage-вызов попадёт в hot-path. Раньше тот же check жил в
``LocalFSStorage.__init__`` через ``warnings.warn`` — оператор мог
пропустить warning, а сам warning срабатывал при первом instantiate,
а не при старте приложения.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from src.backend.core.interfaces.storage import ObjectStorage
from src.backend.core.logging import get_logger

__all__ = ("get_local_fs_storage", "get_object_storage")

logger = get_logger(__name__)


def _enforce_local_fs_safe_in_prod() -> None:
    """Composition root guard: LocalFS недопустим в production-окружении.

    При ``settings.app.environment == "production"`` поднимает
    :class:`ProductionConfigError` (RuntimeError-subclass с одним
    :class:`ConfigViolation`). Это fail-stop на этапе composition root
    (factory вызывается из ``service_setup.register_all_services`` →
    ``run_startup`` → lifespan), до первого hot-path вызова
    ``LocalFSStorage.upload``/``download``.

    Если Settings недоступен (dev_light / unit-test без полного
    config-bootstrap'а) — guard пропускает (return без raise). Это
    сознательно: false-positive fail-stop в dev-окружении хуже, чем
    missing guard в экзотическом test-runner'е.

    Singleton-cached factory (``lru_cache``) гарантирует, что guard
    срабатывает один раз за lifetime процесса — повторные вызовы
    :func:`get_object_storage` короткозамыкают на cached instance.
    """
    try:
        from src.backend.core.config.settings import settings
        from src.backend.core.config.validator._helpers import (
            PRODUCTION_ENV,
            ConfigSeverity,
            ConfigViolation,
            ProductionConfigError,
        )
    except Exception:
        # Settings/validator недоступны → не можем судить; пропускаем
        # (dev_light path, см. docstring).
        return

    env = getattr(getattr(settings, "app", None), "environment", None)
    if env != PRODUCTION_ENV:
        return

    violation = ConfigViolation(
        severity=ConfigSeverity.CRITICAL,
        code="storage.local_in_prod",
        message=(
            "LocalFS storage активирован в production-окружении: "
            "нет шифрования, репликации, CDN; presigned_url отдаёт "
            "file://-only URI, недоступный из браузера."
        ),
        field="storage.provider",
        recommendation=(
            "Указать FS_PROVIDER=minio/aws/other с валидным endpoint/bucket, "
            "либо переключить APP_ENVIRONMENT=development для dev-стенда."
        ),
        context={"environment": env, "provider": "local"},
    )
    raise ProductionConfigError((violation,))


@lru_cache(maxsize=1)
def get_local_fs_storage() -> ObjectStorage:
    """LocalFS-backend singleton.

    Путь берётся из ``settings.storage.local_storage_path`` если задан;
    иначе — ``var/storage``.
    """
    # Composition root fail-stop guard: блокирует LocalFS в production.
    # В dev/staging — no-op (см. _enforce_local_fs_safe_in_prod).
    _enforce_local_fs_safe_in_prod()

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

    В production-окружении попытка получить bare LocalFS или упасть
    на LocalFS-fallback поднимает :class:`ProductionConfigError` через
    :func:`_enforce_local_fs_safe_in_prod` — guard срабатывает на уровне
    composition root, до первого hot-path вызова.
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
    # Guard для secondary LocalFS (composition root fail-stop в prod).
    _enforce_local_fs_safe_in_prod()
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
