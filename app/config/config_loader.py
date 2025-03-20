from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, ClassVar, Dict, Tuple, Type

from dotenv import load_dotenv
from pydantic.fields import FieldInfo
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

from app.config.constants import consts


__all__ = ("BaseSettingsWithLoader",)


load_dotenv(consts.ROOT_DIR / ".env")


class FilteredSettingsSource(PydanticBaseSettingsSource, ABC):
    """Abstract base class for filtered settings sources."""

    def __init__(self, settings_cls: Type[BaseSettings]):
        super().__init__(settings_cls)
        self.yaml_group = settings_cls.yaml_group  # type: ignore
        self.model_fields = settings_cls.model_fields.keys()

    def get_field_value(
        self, field: FieldInfo, field_name: str
    ) -> Tuple[Any, str, bool]:
        return (None, field_name, False)

    def __call__(self) -> Dict[str, Any]:
        try:
            raw_data = self._load_data()

            return self._filter_data(raw_data)
        except Exception as exc:
            self._handle_error(exc)
            return {}

    def _filter_data(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        """Filter data using model fields."""
        if self.yaml_group:
            group_data = raw_data.get(self.yaml_group, {})
        else:
            group_data = raw_data

        return {k: v for k, v in group_data.items() if k in self.model_fields}

    @abstractmethod
    def _load_data(self) -> Dict[str, Any]:
        """Load raw data from source."""
        pass

    def _handle_error(self, error: Exception):
        """Handle errors during data loading."""
        from app.utils.logging_service import app_logger

        app_logger.warning(f"Error in {self.__class__.__name__}: {error}")


class YamlConfigSettingsLoader(FilteredSettingsSource):
    """YAML config loader with filtering."""

    def __init__(
        self,
        settings_cls: Type[BaseSettings],
        yaml_path: Path = consts.ROOT_DIR / "config.yml",
    ):
        super().__init__(settings_cls)
        self.yaml_path = yaml_path

    def _load_data(self) -> Dict[str, Any]:
        """Load and parse YAML configuration file."""
        from yaml import safe_load

        try:
            with open(self.yaml_path) as f:
                return safe_load(f) or {}
        except FileNotFoundError:
            return {}
        except Exception as exc:
            raise RuntimeError(f"YAML loading error: {str(exc)}") from exc


class VaultConfigSettingsSource(FilteredSettingsSource):
    """Vault config loader with filtering."""

    def _load_data(self) -> Dict[str, Any]:
        """Load data from Vault."""
        from os import getenv

        from hvac import Client

        vault_addr = getenv("VAULT_ADDR")
        vault_token = getenv("VAULT_TOKEN")
        vault_secret_path = getenv("VAULT_SECRET_PATH")

        if not all([vault_addr, vault_token, vault_secret_path]):
            return {}

        try:
            client = Client(url=vault_addr, token=vault_token)
            if not client.is_authenticated():
                return {}

            response = client.secrets.kv.v2.read_secret_version(
                path=vault_secret_path
            )
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
        settings_cls: Type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> Tuple[PydanticBaseSettingsSource, ...]:
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
            raise ValueError(
                "Subclasses must define `yaml_group` class variable"
            )

        return (
            init_settings,
            env_settings,
            VaultConfigSettingsSource(settings_cls),
            YamlConfigSettingsLoader(settings_cls),
            dotenv_settings,
            file_secret_settings,
        )
