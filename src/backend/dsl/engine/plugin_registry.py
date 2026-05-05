"""Реестр процессорных плагинов — динамическая загрузка.

Позволяет регистрировать кастомные процессоры в runtime
без изменения исходного кода. Плагины загружаются из
Python-модулей по dotted path.

Использование:
    registry = get_processor_plugin_registry()
    registry.register("my_custom", "my_package.processors.MyProcessor")

    # Теперь доступно в YAML hot reload:
    # processors:
    #   - type: my_custom
    #     param1: value1
"""

import importlib
import logging
from typing import Any

from src.backend.dsl.engine.processors import BaseProcessor

__all__ = ("ProcessorPluginRegistry", "get_processor_plugin_registry")

logger = logging.getLogger("dsl.plugins")


class ProcessorPluginRegistry:
    """Реестр кастомных процессоров."""

    def __init__(self) -> None:
        self._plugins: dict[str, type[BaseProcessor]] = {}

    def register(self, name: str, dotted_path: str) -> None:
        """Регистрирует процессор по dotted path.

        Args:
            name: Короткое имя (для YAML, builder).
            dotted_path: Полный путь к классу (``pkg.module.ClassName``).
        """
        module_path, class_name = dotted_path.rsplit(".", 1)
        module = importlib.import_module(module_path)
        cls = getattr(module, class_name)

        if not (isinstance(cls, type) and issubclass(cls, BaseProcessor)):
            raise TypeError(f"{dotted_path} is not a BaseProcessor subclass")

        self._plugins[name] = cls
        logger.info("Processor plugin registered: %s → %s", name, dotted_path)

    def register_class(self, name: str, cls: type[BaseProcessor]) -> None:
        """Регистрирует класс процессора напрямую."""
        self._plugins[name] = cls

    def get(self, name: str) -> type[BaseProcessor] | None:
        """Возвращает класс процессора по имени."""
        return self._plugins.get(name)

    def create(self, name: str, **kwargs: Any) -> BaseProcessor:
        """Создаёт экземпляр процессора по имени.

        Args:
            name: Имя зарегистрированного процессора.
            **kwargs: Параметры конструктора.

        Raises:
            KeyError: Процессор не зарегистрирован.
        """
        cls = self._plugins.get(name)
        if cls is None:
            raise KeyError(f"Processor plugin '{name}' not registered")
        return cls(**kwargs)

    def list_plugins(self) -> dict[str, str]:
        """Возвращает {name: class_name}."""
        return {name: cls.__name__ for name, cls in sorted(self._plugins.items())}

    def is_registered(self, name: str) -> bool:
        return name in self._plugins


from src.backend.core.di import app_state_singleton


@app_state_singleton("plugin_registry", ProcessorPluginRegistry)
def get_processor_plugin_registry() -> ProcessorPluginRegistry:
    """Возвращает ProcessorPluginRegistry из app.state или lazy-init fallback."""
