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


_DEFAULT_PROFILE_NAME = "dev"


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
    """YAML config loader: грузит конфигурацию из ``config_profiles/``.

    Источник истины — каталог ``config_profiles/``. Базовый набор живёт
    в ``config_profiles/dev.yml`` (полный набор всех ключей). Профили
    ``prod``/``staging``/``dev_light`` — overlay поверх dev через
    deep-merge.

    Логика:
    - active profile == ``dev`` → только ``dev.yml``;
    - active profile != ``dev`` → ``dev.yml`` (base) + ``{profile}.yml``
      (overlay) через :func:`_deep_merge`.

    Отсутствие профильного файла не считается ошибкой (overlay
    игнорируется); отсутствие base ``dev.yml`` — фатальная ошибка.
    """

    def __init__(
        self,
        settings_cls: type[BaseSettings],
        profiles_dir: Path | None = None,
    ):
        super().__init__(settings_cls)
        self.profiles_dir = profiles_dir or _REPO_ROOT / "config_profiles"

    def _load_data(self) -> dict[str, Any]:
        """Загружает базовый профиль и накладывает overlay активного."""
        from yaml import safe_load

        def _read(path: Path) -> dict[str, Any]:
            try:
                with open(path) as f:
                    return safe_load(f) or {}
            except FileNotFoundError:
                return {}
            except Exception as exc:
                raise RuntimeError(f"YAML loading error ({path}): {exc}") from exc

        base_path = self.profiles_dir / f"{_DEFAULT_PROFILE_NAME}.yml"
        base = _read(base_path)
        profile = get_active_profile()
        if profile.value == _DEFAULT_PROFILE_NAME:
            return base

        overlay_path = self.profiles_dir / f"{profile.value}.yml"
        overlay = _read(overlay_path)
        return _deep_merge(base, overlay) if overlay else base


class VaultConfigSettingsSource(FilteredSettingsSource):
    """Vault config loader with filtering.

    Активируется только если в окружении заданы все три переменных
    (``VAULT_ADDR``, ``VAULT_TOKEN``, ``VAULT_SECRET_PATH``) и
    ``VAULT_ENABLED`` не выставлен в ``false``. На профиле
    ``dev_light`` Vault отключают через ``VAULT_ENABLED=false``,
    чтобы не получать сетевые ошибки при отсутствии серверa.
    """

    def _load_data(self) -> dict[str, Any]:
        """Load data from Vault."""
        from os import getenv

        if getenv("VAULT_ENABLED", "true").strip().lower() in {"0", "false", "no"}:
            return {}

        # На профиле dev_light Vault недоступен по умолчанию — отключаем
        # без необходимости явного ``VAULT_ENABLED=false``.
        if get_active_profile().value == "dev_light":
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
