"""Реестр action-обработчиков для DSL-маршрутов.

Предоставляет централизованное хранилище и dispatch
action-команд. Каждый action привязан к сервису и методу,
которые вызываются при поступлении ``ActionCommandSchema``.

Wave 14.1.B (Phase B) — расширение реестра под Gateway-функциональность:

* parallel storage метаданных (:class:`ActionMetadata`) рядом с
  существующим хранилищем :class:`ActionHandlerSpec`;
* регистрация middleware (:class:`ActionMiddleware`);
* новые методы :meth:`register_with_metadata`, :meth:`get_metadata`,
  :meth:`list_metadata`, :meth:`register_middleware`,
  :meth:`list_middleware`.

Backward compatibility:

* :meth:`register` и :meth:`register_many` сохраняют сигнатуры —
  при вызове автоматически создаётся минимальная
  :class:`ActionMetadata` (только ``action`` + ``input_model`` из
  ``payload_model``).
* :meth:`dispatch` не меняется (легаси контракт ``ActionDispatcher``).
"""

import inspect
from dataclasses import dataclass
from typing import Any, Callable

from pydantic import BaseModel

from src.core.interfaces.action_dispatcher import ActionMetadata, ActionMiddleware
from src.schemas.invocation import ActionCommandSchema

__all__ = ("ActionHandlerSpec", "ActionHandlerRegistry", "action_handler_registry")


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

    Wave 14.1.B: дополнительно хранит ``action_name`` ->
    :class:`ActionMetadata` (parallel storage) и упорядоченный
    список middleware. Метаданные используются Gateway-слоем
    (W14.1.A контракт :class:`ActionGatewayDispatcher`) и developer
    portal'ом для автоматической документации.
    """

    def __init__(self) -> None:
        self._handlers: dict[str, ActionHandlerSpec] = {}
        self._metadata: dict[str, ActionMetadata] = {}
        self._middleware: list[ActionMiddleware] = []

    def register(
        self,
        *,
        action: str,
        service_getter: Callable[[], Any],
        service_method: str,
        payload_model: type[BaseModel] | None = None,
    ) -> None:
        """Регистрирует один action-обработчик.

        Если метаданные ``action`` ещё не зарегистрированы — создаётся
        минимальная :class:`ActionMetadata` (с ``input_model =
        payload_model``). Уже сохранённые метаданные не перезаписываются —
        это позволяет сначала вызвать :meth:`register_with_metadata` с
        полной декларацией, а затем (например, из
        ``setup.register_action_handlers``) повторно вызвать
        :meth:`register` для привязки к сервису без потери метаданных.

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
        if action not in self._metadata:
            self._metadata[action] = ActionMetadata(
                action=action, input_model=payload_model
            )

    def register_many(self, specs: list[ActionHandlerSpec]) -> None:
        """Регистрирует несколько action-обработчиков.

        Минимальные метаданные создаются по тем же правилам, что и
        в :meth:`register`.

        Args:
            specs: Список спецификаций для регистрации.
        """
        for spec in specs:
            self._handlers[spec.action] = spec
            if spec.action not in self._metadata:
                self._metadata[spec.action] = ActionMetadata(
                    action=spec.action, input_model=spec.payload_model
                )

    def register_with_metadata(
        self,
        *,
        action: str,
        handler: Callable[..., Any] | ActionHandlerSpec | None,
        metadata: ActionMetadata,
    ) -> None:
        """Регистрирует action вместе с расширенной :class:`ActionMetadata`.

        Используется Gateway-слоем и адаптерами (например,
        ``ActionRouterBuilder``) для регистрации action с полной
        декларацией метаданных.

        Args:
            action: Уникальное имя действия.
            handler: Один из вариантов:

                * :class:`ActionHandlerSpec` — будет сохранён в
                  ``self._handlers`` как обычно;
                * любой ``Callable`` — будет обёрнут как handler
                  без привязки к сервису (используется для
                  metadata-only регистраций, когда сам диспатч
                  обрабатывается транспортом, например,
                  FastAPI-эндпоинтом);
                * ``None`` — регистрация только метаданных
                  (handler уже зарегистрирован отдельно или
                  будет зарегистрирован позже через
                  :meth:`register`).

        Raises:
            ValueError: Если ``metadata.action`` не совпадает с
                переданным ``action``.
        """
        if metadata.action != action:
            raise ValueError(
                f"metadata.action={metadata.action!r} != action={action!r}"
            )

        if isinstance(handler, ActionHandlerSpec):
            self._handlers[action] = handler
        elif handler is not None and not isinstance(handler, ActionHandlerSpec):
            # Сохраняем callable как обёртку: service_getter возвращает
            # объект-носитель, у которого ``__call__`` — наш handler.
            # Однако чаще всего сюда приходит handler=None (metadata-only)
            # либо ActionHandlerSpec. Этот ветке оставляем для будущих
            # сценариев — не пытаемся синтезировать сервис «на лету».
            raise TypeError(
                "handler must be ActionHandlerSpec or None; "
                f"got {type(handler).__name__}"
            )

        self._metadata[action] = metadata

    def get_metadata(self, action: str) -> ActionMetadata | None:
        """Возвращает метаданные action.

        Args:
            action: Имя действия.

        Returns:
            :class:`ActionMetadata` или ``None``, если action не
            зарегистрирован.
        """
        return self._metadata.get(action)

    def list_metadata(self, transport: str | None = None) -> tuple[ActionMetadata, ...]:
        """Возвращает список метаданных всех зарегистрированных actions.

        Args:
            transport: Если задан — возвращаются только метаданные,
                чей ``transports`` содержит указанный транспорт.
                Если ``None`` — возвращаются все.

        Returns:
            Кортеж :class:`ActionMetadata`, отсортированный по
            ``action``.
        """
        items = sorted(self._metadata.values(), key=lambda m: m.action)
        if transport is None:
            return tuple(items)
        return tuple(m for m in items if transport in m.transports)

    def register_middleware(self, middleware: ActionMiddleware) -> None:
        """Регистрирует middleware в конце цепочки.

        Порядок регистрации = порядок вызова. Middleware вызывается
        Gateway-диспетчером (Phase C), реестр лишь хранит цепочку.

        Args:
            middleware: Реализация :class:`ActionMiddleware`.
        """
        self._middleware.append(middleware)

    def list_middleware(self) -> tuple[ActionMiddleware, ...]:
        """Возвращает кортеж зарегистрированных middleware в порядке регистрации."""
        return tuple(self._middleware)

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
        """Очищает реестр обработчиков, метаданные и middleware."""
        self._handlers.clear()
        self._metadata.clear()
        self._middleware.clear()


action_handler_registry = ActionHandlerRegistry()
