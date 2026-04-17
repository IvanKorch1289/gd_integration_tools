"""Централизованный реестр сервисов.

Предоставляет единую точку доступа ко всем бизнес-сервисам
приложения. Сервисы регистрируются с lazy-фабрикой и
создаются при первом обращении.
"""

import threading
from typing import Any, Callable

__all__ = ("ServiceRegistry", "service_registry")


class ServiceRegistry:
    """Реестр сервисов с lazy-инициализацией и потокобезопасностью."""

    def __init__(self) -> None:
        self._factories: dict[str, Callable[[], Any]] = {}
        self._lock = threading.Lock()

    def register(self, name: str, factory: Callable[[], Any]) -> None:
        """Регистрирует фабрику сервиса.

        Args:
            name: Уникальное имя сервиса (например, ``orders``).
            factory: Callable, возвращающий экземпляр сервиса.
        """
        self._factories[name] = factory

    def get(self, name: str) -> Any:
        """Возвращает экземпляр сервиса по имени.

        Вызывает фабрику при каждом обращении — сами фабрики
        уже обёрнуты в ``@singleton``, поэтому дублирования нет.

        Args:
            name: Имя зарегистрированного сервиса.

        Returns:
            Экземпляр сервиса.

        Raises:
            KeyError: Если сервис не зарегистрирован.
        """
        try:
            factory = self._factories[name]
        except KeyError:
            raise KeyError(
                f"Сервис '{name}' не зарегистрирован. "
                f"Доступные: {', '.join(self.list_services())}"
            ) from None

        return factory()

    def list_services(self) -> list[str]:
        """Возвращает список зарегистрированных имён сервисов."""
        return sorted(self._factories.keys())

    def is_registered(self, name: str) -> bool:
        """Проверяет, зарегистрирован ли сервис."""
        return name in self._factories

    def clear(self) -> None:
        """Очищает реестр."""
        self._factories.clear()


service_registry = ServiceRegistry()
