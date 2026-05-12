"""Реестр процессорных плагинов — устаревший API (deprecation-shim, Stage 3).

Старый API сохраняется для обратной совместимости, но внутри делегирует
во новый :class:`src.backend.dsl.registry.ProcessorRegistry`. При каждом
вызове ``register`` / ``register_class`` пишется ``DeprecationWarning``.

Новый код должен использовать::

    from src.backend.dsl.registry import processor, get_processor_registry

    @processor("my_custom", namespace="my_plugin")
    class MyProcessor(BaseProcessor):
        ...

См. план: ``/home/user/.claude/plans/replicated-seeking-panda.md``
(раздел A5/Stage 3).
"""

from __future__ import annotations

import importlib
import logging
import warnings
from typing import Any

from src.backend.core.di import app_state_singleton
from src.backend.dsl.engine.processors import BaseProcessor
from src.backend.dsl.registry import (
    ProcessorNotFoundError,
    ProcessorSpec,
    get_processor_registry,
)

__all__ = ("ProcessorPluginRegistry", "get_processor_plugin_registry")

logger = logging.getLogger("dsl.plugins")

_DEPRECATION_NAMESPACE = "legacy_plugin"
_DEPRECATION_MSG = (
    "ProcessorPluginRegistry устарел. Используйте "
    "src.backend.dsl.registry.processor (декоратор) и "
    "src.backend.dsl.registry.get_processor_registry()."
)


class ProcessorPluginRegistry:
    """Устаревший фасад поверх нового :class:`ProcessorRegistry`.

    Все операции делегируют в global-singleton :class:`ProcessorRegistry`.
    Регистрации пишутся в namespace ``legacy_plugin`` для отделения от
    новых записей с явным namespacing'ом.
    """

    def __init__(self) -> None:
        self._registry = get_processor_registry()

    def register(self, name: str, dotted_path: str) -> None:
        """Регистрирует процессор по dotted path (deprecation: см. модульный docstring)."""

        warnings.warn(_DEPRECATION_MSG, DeprecationWarning, stacklevel=2)

        module_path, class_name = dotted_path.rsplit(".", 1)
        module = importlib.import_module(module_path)
        cls = getattr(module, class_name)

        if not (isinstance(cls, type) and issubclass(cls, BaseProcessor)):
            raise TypeError(f"{dotted_path} is not a BaseProcessor subclass")

        self._register_class_internal(name, cls)
        logger.info("Processor plugin registered (legacy): %s → %s", name, dotted_path)

    def register_class(self, name: str, cls: type[BaseProcessor]) -> None:
        """Регистрирует класс процессора напрямую (deprecation: см. модульный docstring)."""

        warnings.warn(_DEPRECATION_MSG, DeprecationWarning, stacklevel=2)
        self._register_class_internal(name, cls)

    def _register_class_internal(self, name: str, cls: type[BaseProcessor]) -> None:
        fqn = f"{_DEPRECATION_NAMESPACE}:{name}"
        spec = ProcessorSpec(
            name=name,
            namespace=_DEPRECATION_NAMESPACE,
            cls=cls,
            replaces=fqn if fqn in self._registry else None,
            meta={"legacy": True},
        )
        self._registry.register(spec)

    def get(self, name: str) -> type[BaseProcessor] | None:
        """Возвращает класс процессора по короткому имени или None."""

        try:
            spec = self._registry.get(f"{_DEPRECATION_NAMESPACE}:{name}")
        except ProcessorNotFoundError:
            return None
        return spec.cls

    def create(self, name: str, **kwargs: Any) -> BaseProcessor:
        """Создаёт экземпляр процессора по имени."""

        cls = self.get(name)
        if cls is None:
            raise KeyError(f"Processor plugin '{name}' not registered")
        return cls(**kwargs)

    def list_plugins(self) -> dict[str, str]:
        """Возвращает {name: class_name} для legacy-namespace."""

        return {
            spec.name: spec.cls.__name__
            for spec in sorted(
                self._registry.list_by_namespace(_DEPRECATION_NAMESPACE),
                key=lambda s: s.name,
            )
        }

    def is_registered(self, name: str) -> bool:
        return f"{_DEPRECATION_NAMESPACE}:{name}" in self._registry


@app_state_singleton("plugin_registry", ProcessorPluginRegistry)
def get_processor_plugin_registry() -> ProcessorPluginRegistry:
    """Возвращает ProcessorPluginRegistry из app.state или lazy-init fallback."""
