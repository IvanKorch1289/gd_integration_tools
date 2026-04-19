"""Реестр action-обработчиков для DSL-маршрутов.

Предоставляет централизованное хранилище и dispatch
action-команд. Каждый action привязан к сервису и методу,
которые вызываются при поступлении ``ActionCommandSchema``.
"""

import inspect
from dataclasses import dataclass
from typing import Any, Callable

from pydantic import BaseModel

from app.schemas.invocation import ActionCommandSchema

__all__ = (
    "ActionHandlerSpec",
    "ActionHandlerRegistry",
    "action_handler_registry",
)


@dataclass(slots=True)
class ActionHandlerSpec:
    """Спецификация одного action-обработчика.

    Attrs:
        action: Уникальное имя действия (например,
            ``orders.create_skb_order``).
        service_getter: Фабрика, возвращающая экземпляр сервиса.
        service_method: Имя метода сервиса для вызова.
        payload_model: Pydantic-модель для валидации payload.
            Если указана, ``payload`` из команды будет
            провалидирован и развёрнут в kwargs.
    """

    action: str
    service_getter: Callable[[], Any]
    service_method: str
    payload_model: type[BaseModel] | None = None


class ActionHandlerRegistry:
    """Реестр и диспетчер action-обработчиков.

    Хранит ``action_name`` -> ``ActionHandlerSpec`` и предоставляет
    единый ``dispatch()`` для вызова из любого entrypoint
    (HTTP, stream, gRPC, DSL pipeline).
    """

    def __init__(self) -> None:
        self._handlers: dict[str, ActionHandlerSpec] = {}

    def register(
        self,
        *,
        action: str,
        service_getter: Callable[[], Any],
        service_method: str,
        payload_model: type[BaseModel] | None = None,
    ) -> None:
        """Регистрирует один action-обработчик.

        Args:
            action: Уникальное имя действия.
            service_getter: Фабрика сервиса.
            service_method: Имя метода сервиса.
            payload_model: Модель валидации payload.
        """
        self._handlers[action] = ActionHandlerSpec(
            action=action,
            service_getter=service_getter,
            service_method=service_method,
            payload_model=payload_model,
        )

    def register_many(self, specs: list[ActionHandlerSpec]) -> None:
        """Регистрирует несколько action-обработчиков.

        Args:
            specs: Список спецификаций для регистрации.
        """
        for spec in specs:
            self._handlers[spec.action] = spec

    async def dispatch(self, command: ActionCommandSchema) -> Any:
        """Выполняет action-команду.

        Находит обработчик по ``command.action``, валидирует
        payload (если указана ``payload_model``), вызывает
        метод сервиса и возвращает результат.

        Args:
            command: Команда для выполнения.

        Returns:
            Результат вызова метода сервиса.

        Raises:
            KeyError: Если action не зарегистрирован.
            ValidationError: Если payload не прошёл валидацию.
        """
        spec = self._handlers[command.action]

        service = spec.service_getter()
        method = getattr(service, spec.service_method)

        if spec.payload_model is not None and command.payload:
            validated = spec.payload_model.model_validate(command.payload)
            kwargs = {
                field_name: getattr(validated, field_name)
                for field_name in validated.model_fields
                if getattr(validated, field_name) is not None
            }
        else:
            kwargs = command.payload or {}

        result = method(**kwargs)
        if inspect.isawaitable(result):
            result = await result

        return result

    def is_registered(self, action: str) -> bool:
        """Проверяет наличие action-обработчика.

        Args:
            action: Имя действия.

        Returns:
            ``True`` если обработчик зарегистрирован.
        """
        return action in self._handlers

    def list_actions(self) -> tuple[str, ...]:
        """Возвращает список зарегистрированных action-имён.

        Returns:
            Отсортированный кортеж имён.
        """
        return tuple(sorted(self._handlers.keys()))

    def clear(self) -> None:
        """Очищает реестр обработчиков."""
        self._handlers.clear()


action_handler_registry = ActionHandlerRegistry()
