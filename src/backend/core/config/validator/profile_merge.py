"""Merged-валидация профиля конфигурации (ADR-0375, wave 14 — ЧАСТЬ B).

Зачем
-----
``manage.py validate-profile`` проверял ТОЛЬКО overlay-файл профиля. Но
приложение читает СЛИЯННЫЙ конфиг (``base.yml`` + overlay через
``_deep_merge`` в ``YamlConfigSettingsLoader``), поэтому инварианты,
объявленные в ``base.yml`` (например ``http.ssl_verify``,
``vault.addr``, ``graphql.enable_introspection``), были не видны
валидатору — «зелёный» отчёт не означал «конфиг валиден».

Этот модуль собирает merged-конфиг ровно так же, как это делает рантайм,
и прогоняет по нему :class:`ConfigValidator`.

Особенности
-----------
* секреты не нужны: секции собираются через ``model_construct`` — берутся
  значения из YAML, а отсутствующие (секретные) поля остаются на дефолтах
  модели; ``model_construct`` не валидирует, поэтому ``ValidationError``
  из-за отсутствующих ``password``/``secret_key`` не возникает;
* ``features`` — отдельная группа (в корневом ``Settings`` её нет),
  поэтому контейнер настроек профиля объявляет её явно.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic_settings import BaseSettings

from src.backend.core.config.base import AppBaseSettings
from src.backend.core.config.config_loader import _deep_merge, repo_root
from src.backend.core.config.database import DatabaseConnectionSettings
from src.backend.core.config.features import FeatureFlags
from src.backend.core.config.security import SecureSettings
from src.backend.core.config.services.cache import RedisSettings
from src.backend.core.config.validator._helpers import ConfigSeverity, ConfigViolation
from src.backend.core.config.vault import VaultSettings
from src.backend.core.config.waf import WafSettings

__all__ = (
    "ProfileSettings",
    "build_profile_settings",
    "load_profile_yaml",
    "merge_profile_yaml",
    "validate_profile_config",
)


class ProfileSettings(BaseSettings):
    """Минимальный контейнер секций, которые проверяет ``ConfigValidator``.

    Собран из merged-YAML через ``model_construct`` — без валидации и без
    обращения к env/Vault: CLI-валидация профиля не должна требовать
    секретов (их подставляет рантайм).
    """

    app: AppBaseSettings
    secure: SecureSettings
    vault: VaultSettings
    database: DatabaseConnectionSettings
    redis: RedisSettings
    features: FeatureFlags


def _profiles_dir(profiles_dir: Path | None = None) -> Path:
    """Каталог с YAML-профилями.

    Args:
        profiles_dir: Явный каталог (для тестов). По умолчанию —
            ``<repo_root>/config_profiles``.

    Returns:
        Путь к каталогу профилей.
    """
    return profiles_dir if profiles_dir is not None else repo_root() / "config_profiles"


def load_profile_yaml(profile: str, profiles_dir: Path | None = None) -> dict[str, Any]:
    """Читает overlay-файл профиля.

    Args:
        profile: Имя профиля (``dev``/``dev_light``/``staging``/``prod``).
        profiles_dir: Каталог профилей (по умолчанию — репозиторный).

    Returns:
        Разобранный mapping (пустой dict для пустого файла).

    Raises:
        FileNotFoundError: Файла профиля нет.
        RuntimeError: YAML невалиден.

    """
    import yaml

    path = _profiles_dir(profiles_dir) / f"{profile}.yml"
    if not path.is_file():
        raise FileNotFoundError(str(path))
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
    except yaml.YAMLError as exc:
        raise RuntimeError(f"Invalid YAML in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise RuntimeError(f"Profile must be a YAML mapping: {path}")
    return data


def merge_profile_yaml(profile: str, profiles_dir: Path | None = None) -> dict[str, Any]:
    """Сливает ``base.yml`` + overlay профиля (как в ``config_loader``).

    Args:
        profile: Имя профиля.
        profiles_dir: Каталог профилей (по умолчанию — репозиторный).

    Returns:
        Итоговый конфиг после слияния.

    Raises:
        FileNotFoundError: Нет base.yml или overlay-файла профиля.

    """
    directory = _profiles_dir(profiles_dir)
    base_path = directory / "base.yml"
    if not base_path.is_file():
        raise FileNotFoundError(str(base_path))
    import yaml

    with base_path.open("r", encoding="utf-8") as fh:
        base = yaml.safe_load(fh) or {}
    if not isinstance(base, dict):
        raise RuntimeError(f"Base profile must be a YAML mapping: {base_path}")
    return _deep_merge(base, load_profile_yaml(profile, profiles_dir))


def _construct(model_cls: type[Any], section: dict[str, Any] | None) -> Any:
    """Собирает экземпляр модели из YAML-секции (без валидации).

    Args:
        model_cls: Pydantic-модель настроек.
        section: YAML-секция (может быть пустой).

    Returns:
        Экземпляр модели с значениями из YAML и дефолтами модели.
    """
    values = {
        key: value
        for key, value in (section or {}).items()
        if key in model_cls.model_fields
    }
    return model_cls.model_construct(**values)


def build_profile_settings(merged: dict[str, Any]) -> ProfileSettings:
    """Собирает контейнер настроек профиля из merged-конфига.

    Args:
        merged: Слияние ``base.yml`` + overlay профиля.

    Returns:
        Экземпляр :class:`ProfileSettings` для :class:`ConfigValidator`.

    """
    return ProfileSettings.model_construct(
        app=_construct(AppBaseSettings, merged.get("app")),
        secure=_construct(SecureSettings, merged.get("security")),
        vault=_construct(VaultSettings, merged.get("vault")),
        database=_construct(DatabaseConnectionSettings, merged.get("database")),
        redis=_construct(RedisSettings, merged.get("redis")),
        features=_construct(FeatureFlags, merged.get("features")),
    )


def validate_profile_config(
    profile: str, profiles_dir: Path | None = None
) -> tuple[ConfigViolation, ...]:
    """Валидирует MERGED-конфиг профиля (base + overlay).

    Args:
        profile: Имя профиля.
        profiles_dir: Каталог профилей (по умолчанию — репозиторный).

    Returns:
        Кортеж нарушений, отсортированный по severity
        (CRITICAL → WARNING → INFO).

    """
    from src.backend.core.config.validator import ConfigValidator

    merged = merge_profile_yaml(profile, profiles_dir)
    settings = build_profile_settings(merged)
    waf = _construct(WafSettings, merged.get("waf"))
    try:
        violations = ConfigValidator().validate(settings, waf)
    except AttributeError as exc:
        # Профиль неполон: обязательное поле отсутствует в YAML (например,
        # ``app.enable_swagger``). Это дефект конфигурации, а не сбой CLI —
        # сообщаем его как CRITICAL, а не роняем команду трейсбеком.
        return (
            ConfigViolation(
                severity=ConfigSeverity.CRITICAL,
                code="profile.incomplete",
                message=(
                    f"Профиль {profile} неполон: отсутствует обязательное поле "
                    f"({exc})."
                ),
                field=str(exc),
                recommendation=(
                    "Дополнить config_profiles/base.yml (или overlay профиля) "
                    "недостающими полями."
                ),
            ),
        )
    return tuple(
        sorted(
            violations,
            key=lambda v: (
                0
                if v.severity == ConfigSeverity.CRITICAL
                else 1
                if v.severity == ConfigSeverity.WARNING
                else 2
            ),
        )
    )
