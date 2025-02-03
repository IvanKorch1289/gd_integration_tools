from pathlib import Path
from typing import Any, Dict

import yaml
from copy import deepcopy
from pydantic import BaseModel

from app.config.config_loader import BaseYAMLSettings
from app.utils.logging_service import app_logger


__all__ = (
    "ConfigUpdateRequest",
    "ConfigManager",
)


class ConfigUpdateRequest(BaseModel):
    data: Dict[str, Any]


class ConfigManager:
    def __init__(self, config_path: Path):
        self.config_path = config_path
        self._config = self._load_config()
        self._config_models: Dict[type, Any] = {}  # кэш моделей настроек

    @property
    def current_config(self) -> Dict[str, Any]:
        return deepcopy(self._config)

    def get_settings(self, model: type[BaseYAMLSettings]) -> BaseYAMLSettings:
        if model not in self._config_models:
            self._config_models[model] = model()
        return self._config_models[model]

    def _load_config(self) -> Dict[str, Any]:
        try:
            with open(self.config_path, "r") as f:
                return yaml.safe_load(f) or {}
        except Exception as e:
            app_logger.error(f"Config load error: {str(e)}")
            raise

    def _validate_structure(self, new_data: Dict, existing_data: Dict):
        """Рекурсивная проверка структуры конфига"""
        for key, value in new_data.items():
            if key not in existing_data:
                raise ValueError(f"Invalid key: {key}")
            if isinstance(value, dict):
                if not isinstance(existing_data[key], dict):
                    raise ValueError(f"Key {key} is not a section")
                self._validate_structure(value, existing_data[key])

    def update_config(self, new_data: Dict[str, Any]) -> Dict[str, Any]:
        """Основной метод обновления конфигурации"""
        # Валидация структуры
        self._validate_structure(new_data, self._config)

        # Обновление конфига в памяти
        updated_config = deepcopy(self._config)
        self._deep_update(updated_config, new_data)

        # Сохранение в файл
        self._save_to_file(updated_config)

        # Обновление кэша моделей
        self._reload_settings_models()

        return self.current_config

    def _deep_update(self, target: Dict, update: Dict):
        """Рекурсивное обновление словаря"""
        for key, value in update.items():
            if isinstance(value, dict):
                self._deep_update(target.setdefault(key, {}), value)
            else:
                target[key] = value

    def _save_to_file(self, config: Dict):
        """Атомарное сохранение конфига"""
        try:
            temp_path = self.config_path.with_suffix(".tmp")
            with open(temp_path, "w") as f:
                yaml.safe_dump(config, f, sort_keys=False)
            temp_path.replace(self.config_path)
        except Exception as e:
            app_logger.error(f"Config save failed: {str(e)}")
            raise

    def _reload_settings_models(self):
        """Перезагрузка всех зарегистрированных моделей настроек"""
        for model in self._config_models:
            self._config_models[model] = model()
