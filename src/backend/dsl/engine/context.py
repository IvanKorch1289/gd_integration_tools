import logging
from dataclasses import dataclass, field
from typing import Any

from src.backend.dsl.commands.registry import (
    ActionHandlerRegistry,
    action_handler_registry,
)

__all__ = ("ExecutionContext",)


@dataclass(slots=True)
class ExecutionContext:
    """
    Контекст выполнения DSL-маршрута.

    Хранит зависимости и shared-state, которые нужны процессорам во время
    обработки Exchange, но не должны попадать в payload сообщения.

    Attributes:
        action_registry: Реестр action-команд.
        logger: Опциональный logger для трассировки выполнения.
        state: Общий изменяемый словарь для обмена данными между процессорами.
        route_id: Идентификатор текущего маршрута (для логирования).
    """

    action_registry: ActionHandlerRegistry = action_handler_registry
    logger: logging.Logger | None = None
    route_id: str = ""
    state: dict[str, Any] = field(default_factory=dict)

    def get(self, key: str, default: Any = None) -> Any:
        """
        Возвращает значение из shared-state.

        Args:
            key: Ключ.
            default: Значение по умолчанию.

        Returns:
            Any: Найденное значение или default.
        """
        return self.state.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """
        Сохраняет значение в shared-state.

        Args:
            key: Ключ.
            value: Значение.
        """
        self.state[key] = value
