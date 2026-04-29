from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, ClassVar

from dotenv import load_dotenv
from pydantic.fields import FieldInfo
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

from src.core.config.constants import consts
from src.core.config.profile import get_active_profile

__all__ = ("BaseSettingsWithLoader",)


def _resolve_repo_root() -> Path:
    """Возвращает корень репозитория (директория с ``pyproject.toml``).

    ``consts.ROOT_DIR`` исторически указывает на ``src/`` — для конфигов
    нужен родитель (где лежит ``config_profiles/``). Поиск идёт вверх от
    текущего файла; при провале возвращается родитель ``ROOT_DIR`` как
    лучший доступный fallback.
    """
    current = Path(__file__).resolve()
    for parent in (current, *current.parents):
        if (parent / "pyproject.toml").is_file():
            return parent
    return consts.ROOT_DIR.parent


_REPO_ROOT: Path = _resolve_repo_root()


load_dotenv(_REPO_ROOT / ".env")


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Рекурсивно сливает ``overlay`` поверх ``base``, не мутируя исходники."""
    merged: dict[str, Any] = dict(base)
    for key, value in overlay.items():
        existing = merged.get(key)
        if isinstance(existing, dict) and isinstance(value, dict):
            merged[key] = _deep_merge(existing, value)
        else:
            merged[key] = value
    return merged


def _read_yaml(path: Path) -> dict[str, Any]:
    """Безопасное чтение YAML-файла. Отсутствие файла → пустой dict."""
    from yaml import safe_load

    try:
        with open(path) as fh:
            data = safe_load(fh) or {}
    except FileNotFoundError:
        return {}
    except Exception as exc:
        raise RuntimeError(f"YAML loading error ({path}): {exc}") from exc
    return data if isinstance(data, dict) else {}


def _is_vault_enabled() -> bool:
    """Решает, активировать ли VaultConfigSettingsSource.

    Приоритет: env-override (``VAULT_ENABLED``) → YAML (``vault.enabled``)
    → значение по умолчанию ``True``. Helper не инстанциирует
    ``VaultSettings`` — это вызвало бы рекурсию через
    ``customise_sources``; YAML читается напрямую.
    """
    from os import getenv

    raw = getenv("VAULT_ENABLED")
    if raw is not None and raw.strip():
        return raw.strip().lower() not in {"0", "false", "no"}
    base = _read_yaml(_REPO_ROOT / "config_profiles" / "base.yml")
    overlay = _read_yaml(
        _REPO_ROOT / "config_profiles" / f"{get_active_profile().value}.yml"
    )
    vault_cfg = _deep_merge(base, overlay).get("vault") or {}
    return bool(vault_cfg.get("enabled", True))


class FilteredSettingsSource(PydanticBaseSettingsSource, ABC):
    """Abstract base class for filtered settings sources."""

    def __init__(self, settings_cls: type[BaseSettings]):
        super().__init__(settings_cls)
        self.yaml_group = settings_cls.yaml_group  # type: ignore
        self.model_fields = settings_cls.model_fields.keys()

    def get_field_value(
        self, field: FieldInfo, field_name: str
    ) -> tuple[Any, str, bool]:
        return (None, field_name, False)

    def __call__(self) -> dict[str, Any]:
        try:
            raw_data = self._load_data()

            return self._filter_data(raw_data)
        except Exception as exc:
            self._handle_error(exc)
            return {}

    def _filter_data(self, raw_data: dict[str, Any]) -> dict[str, Any]:
        """Filter data using model fields."""
        if self.yaml_group:
            group_data = raw_data.get(self.yaml_group, {})
        else:
            group_data = raw_data

        return {k: v for k, v in group_data.items() if k in self.model_fields}

    @abstractmethod
    def _load_data(self) -> dict[str, Any]:
        """Load raw data from source."""
        pass

    def _handle_error(self, error: Exception):
        """Handle errors during data loading."""
        import logging

        logging.getLogger(__name__).error(
            "Ошибка в %s: %s", self.__class__.__name__, error
        )


class YamlConfigSettingsLoader(FilteredSettingsSource):
    """YAML config loader: ``base.yml`` + overlay активного профиля.

    Структура ``config_profiles/``:
        * ``base.yml`` — общие нечувствительные настройки, не зависящие
          от окружения (timeouts, retries, pool_size, encoding и т.д.);
        * ``{profile}.yml`` — env-specific overrides (хосты, порты,
          enabled-флаги для конкретного окружения).

    Финальная конфигурация = ``_deep_merge(base, profile)``. Оба файла
    обязательны — отсутствие любого из них приводит к фатальной ошибке.
    Секреты приходят из env / Vault; в YAML их быть не должно (см.
    ``tools/config_audit.py`` и ``.env.example``).
    """

    def __init__(
        self, settings_cls: type[BaseSettings], profiles_dir: Path | None = None
    ):
        super().__init__(settings_cls)
        self.profiles_dir = profiles_dir or _REPO_ROOT / "config_profiles"

    def _load_data(self) -> dict[str, Any]:
        """Загружает ``base.yml`` и накладывает overlay активного профиля.

        Оба файла обязательны (FileNotFound → RuntimeError); ``_read_yaml``
        здесь оборачивается, чтобы конвертировать отсутствие файла в
        фатальную ошибку (в loader-контексте отсутствие конфига —
        нерабочая ситуация, в отличие от ``_is_vault_enabled``, который
        допускает мягкий fallback).
        """
        base_path = self.profiles_dir / "base.yml"
        profile = get_active_profile()
        overlay_path = self.profiles_dir / f"{profile.value}.yml"
        for path in (base_path, overlay_path):
            if not path.is_file():
                raise RuntimeError(
                    f"Config not found: {path}. "
                    "Ожидается base.yml + {profile}.yml в config_profiles/."
                )
        return _deep_merge(_read_yaml(base_path), _read_yaml(overlay_path))


class VaultConfigSettingsSource(FilteredSettingsSource):
    """Vault config loader with filtering.

    Активируется только если включён через YAML (``vault.enabled: true``)
    или env-override (``VAULT_ENABLED``), и в окружении заданы все три
    переменных ``VAULT_ADDR``/``VAULT_TOKEN``/``VAULT_SECRET_PATH``. На
    профиле ``dev_light`` поставляется overlay ``vault.enabled: false``,
    что отключает источник без необходимости трогать env.
    """

    def _load_data(self) -> dict[str, Any]:
        """Load data from Vault."""
        from os import getenv

        if not _is_vault_enabled():
            return {}

        vault_addr = getenv("VAULT_ADDR")
        vault_token = getenv("VAULT_TOKEN")
        vault_secret_path = getenv("VAULT_SECRET_PATH")

        if not all([vault_addr, vault_token, vault_secret_path]):
            return {}

        from hvac import Client

        try:
            client = Client(url=vault_addr, token=vault_token)
            if not client.is_authenticated():
                return {}

            response = client.secrets.kv.v2.read_secret_version(path=vault_secret_path)
            return response.get("data", {}).get("data", {})
        except Exception as exc:
            raise RuntimeError(f"Vault error: {str(exc)}") from exc


class BaseSettingsWithLoader(BaseSettings):
    """Base class for configuration models with multi-source loading support.

    Combines configuration from:
    - Initialization parameters
    - Environment variables
    - Vault secrets
    - YAML configuration files
    - .env files
    - File-based secrets

    Subclasses must define:
    - `yaml_group`: Name of the YAML configuration section to use
    - `model_config.env_prefix`: Environment variables prefix for settings group
    """

    yaml_group: ClassVar[str | None] = None
    model_config = SettingsConfigDict(env_prefix="", extra="forbid")

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Customize configuration sources and their priority order.

        Priority order (highest first):
        1. Initialization parameters
        2. Environment variables
        3. Vault secrets
        4. YAML configuration
        5. .env file
        6. File-based secrets
        """
        if not cls.yaml_group:
            raise ValueError("Subclasses must define `yaml_group` class variable")

        return (
            init_settings,
            env_settings,
            VaultConfigSettingsSource(settings_cls),
            YamlConfigSettingsLoader(settings_cls),
            dotenv_settings,
            file_secret_settings,
        )
