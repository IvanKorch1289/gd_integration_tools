from pathlib import Path
from typing import Any, ClassVar, Dict, Optional, Tuple, Type

import yaml
from dotenv import load_dotenv
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)
from yaml import YAMLError

from app.config.constants import ROOT_DIR


__all__ = (
    "YamlConfigSettingsLoader",
    "yaml_settings_loader",
    "BaseYAMLSettings",
)

# Load environment variables from .env file
load_dotenv(ROOT_DIR / ".env")


class YamlConfigSettingsLoader:
    """Loader for YAML configuration files with group-based settings retrieval.

    Attributes:
        yaml_path: Path to the YAML configuration file.
    """

    def __init__(self, yaml_path: Path) -> None:
        """Initialize the YAML config loader with specified file path."""
        self.yaml_path = yaml_path

    def __call__(self) -> Dict[str, Any]:
        """Load and parse the entire YAML configuration file.

        Returns:
            Dictionary containing all configuration groups.

        Raises:
            YAMLError: If the file contains invalid YAML syntax.
        """
        try:
            with open(self.yaml_path) as f:
                return yaml.safe_load(f) or {}
        except FileNotFoundError:
            return {}
        except YAMLError as e:
            raise YAMLError(f"Invalid YAML syntax in {self.yaml_path}") from e

    def get_group_settings(self, group: str) -> Dict[str, Any]:
        """Retrieve configuration settings for a specific group.

        Args:
            group: Name of the configuration section to retrieve

        Returns:
            Dictionary of settings for the requested group. Returns empty dict
            if group not found or file is missing.
        """
        try:
            config_data = self.__call__()
            return config_data.get(group, {})
        except (YAMLError, ValueError):
            return {}


# Global YAML settings loader instance configured with default config path
yaml_settings_loader = YamlConfigSettingsLoader(
    yaml_path=ROOT_DIR / "config.yml"
)


class BaseYAMLSettings(BaseSettings):
    """Base class for configuration models combining YAML and environment variables.

    Subclasses must define:
    - `yaml_group`: Name of the YAML configuration section to use
    - `model_config.env_prefix`: Environment variables prefix for the settings group
    """

    # Configuration group name in YAML file (must be set in subclasses)
    yaml_group: ClassVar[Optional[str]] = None

    # Pydantic configuration (should include env_prefix in subclasses)
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
        """Correct signature with all required parameters"""
        if not cls.yaml_group:
            raise ValueError(
                "Subclasses must define `yaml_group` class variable"
            )

        yaml_config = (
            yaml_settings_loader.get_group_settings(cls.yaml_group) or {}
        )
        env_vars = env_settings()
        init_config = init_settings()

        merged_config = {**init_config, **env_vars, **yaml_config}

        return (lambda: merged_config,)
