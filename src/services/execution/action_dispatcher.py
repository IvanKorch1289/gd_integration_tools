"""Реализация ActionDispatcher / ActionGatewayDispatcher (W14.1, W14.1.C).

Двойной контракт:

* :class:`ActionDispatcher` (W14.1, legacy) — принимает
  :class:`ActionCommandSchema` и возвращает «сырой» результат сервиса.
  Используется существующими call sites (Invoker, DSL processors).
* :class:`ActionGatewayDispatcher` (W14.1.A) — принимает
  ``action`` + ``payload`` + :class:`DispatchContext`, возвращает
  унифицированный :class:`ActionResult` envelope, поддерживает
  middleware-цепочку. Используется новым Gateway-слоем.

Middleware-цепочка строится при каждом ``dispatch`` из списка,
зарегистрированного в :class:`ActionHandlerRegistry`. Терминальный
обработчик — вызов ``registry.dispatch(ActionCommandSchema)``;
ошибки маппятся в :class:`ActionResult` с :class:`ActionError`.
"""

from __future__ import annotations

from typing import Any, Mapping

from src.core.interfaces.action_dispatcher import (
    ActionDispatcher,
    ActionError,
    ActionGatewayDispatcher,
    ActionMetadata,
    ActionMiddleware,
    ActionResult,
    DispatchContext,
    MiddlewareNextHandler,
    TransportName,
)
from src.dsl.commands.action_registry import (
    ActionHandlerRegistry,
    action_handler_registry,
)
from src.schemas.invocation import ActionCommandSchema

__all__ = ("DefaultActionDispatcher", "get_action_dispatcher")


class DefaultActionDispatcher(ActionDispatcher, ActionGatewayDispatcher):
    """Делегирует диспетчеризацию singleton-реестру.

    Реализует одновременно:

    * легаси-контракт :class:`ActionDispatcher` — :meth:`dispatch`
      с :class:`ActionCommandSchema`, без middleware-цепочки;
    * расширенный :class:`ActionGatewayDispatcher` — :meth:`dispatch_action`
      с :class:`DispatchContext` + :class:`ActionResult` envelope,
      поверх middleware-цепочки.

    Конструктор принимает реестр явно — тесты могут подменить его на
    изолированный экземпляр без обращения к global state.
    """

    def __init__(self, registry: ActionHandlerRegistry | None = None) -> None:
        self._registry = registry or action_handler_registry

    # ------------------------------------------------------------------ #
    # Legacy ActionDispatcher API                                        #
    # ------------------------------------------------------------------ #

    async def dispatch(
        self,
        command_or_action: ActionCommandSchema | str,
        payload: Mapping[str, Any] | None = None,
        context: DispatchContext | None = None,
    ) -> Any:
        """Унифицированная точка входа.

        Поведение зависит от типа первого аргумента:

        * :class:`ActionCommandSchema` — легаси-режим (W14.1):
          вызывает реестр напрямую, возвращает «сырое» значение
          (без middleware и без envelope).
        * ``str`` (имя action) — Gateway-режим (W14.1.A):
          применяет middleware-цепочку и возвращает
          :class:`ActionResult`.
        """
        if isinstance(command_or_action, ActionCommandSchema):
            # Legacy: payload/context игнорируются, средние — нет.
            return await self._registry.dispatch(command_or_action)

        # Gateway-режим.
        action = command_or_action
        return await self.dispatch_action(
            action,
            payload or {},
            context or DispatchContext(),
        )

    def is_registered(self, action: str) -> bool:
        return self._registry.is_registered(action)

    # ------------------------------------------------------------------ #
    # ActionGatewayDispatcher API                                        #
    # ------------------------------------------------------------------ #

    async def dispatch_action(
        self,
        action: str,
        payload: Mapping[str, Any],
        context: DispatchContext,
    ) -> ActionResult:
        """Gateway-вариант dispatch с middleware-цепочкой.

        Если action не зарегистрирован — возвращает
        :class:`ActionResult` ``success=False`` без вызова middleware
        (невозможно решить, какие middleware применять без метаданных,
        и нечего идемпотентно кэшировать).
        """
        if not self._registry.is_registered(action):
            return ActionResult(
                success=False,
                error=ActionError(
                    code="action_not_found",
                    message=f"Action {action!r} is not registered",
                    recoverable=False,
                ),
            )

        return await self._run_middleware_chain(
            action, payload, context, self._terminal_handler
        )

    def get_metadata(self, action: str) -> ActionMetadata | None:
        return self._registry.get_metadata(action)

    def list_actions(
        self, transport: TransportName | None = None
    ) -> tuple[str, ...]:
        """Список action-имён, опционально отфильтрованный по транспорту."""
        if transport is None:
            return self._registry.list_actions()
        return tuple(m.action for m in self._registry.list_metadata(transport))

    def list_metadata(
        self, transport: TransportName | None = None
    ) -> tuple[ActionMetadata, ...]:
        return self._registry.list_metadata(transport)

    def register_middleware(self, middleware: ActionMiddleware) -> None:
        self._registry.register_middleware(middleware)

    # ------------------------------------------------------------------ #
    # Middleware chain                                                   #
    # ------------------------------------------------------------------ #

    async def _run_middleware_chain(
        self,
        action: str,
        payload: Mapping[str, Any],
        context: DispatchContext,
        terminal: MiddlewareNextHandler,
    ) -> ActionResult:
        """Строит и выполняет middleware-цепочку справа налево.

        Каждое middleware получает ``next_handler``, который оборачивает
        следующее middleware (или ``terminal`` для последнего).
        """
        middlewares = self._registry.list_middleware()
        chain: MiddlewareNextHandler = terminal
        # Оборачиваем с конца, чтобы порядок регистрации = порядок вызова.
        for mw in reversed(middlewares):
            chain = self._wrap(mw, chain)
        return await chain(action, payload, context)

    @staticmethod
    def _wrap(
        middleware: ActionMiddleware,
        next_handler: MiddlewareNextHandler,
    ) -> MiddlewareNextHandler:
        """Превращает (middleware, next) в новый MiddlewareNextHandler."""

        async def _wrapped(
            action: str,
            payload: Mapping[str, Any],
            context: DispatchContext,
        ) -> ActionResult:
            return await middleware(action, payload, context, next_handler)

        return _wrapped

    async def _terminal_handler(
        self,
        action: str,
        payload: Mapping[str, Any],
        context: DispatchContext,
    ) -> ActionResult:
        """Терминальный обработчик: вызов реестра + маппинг в ActionResult."""
        command = ActionCommandSchema(action=action, payload=dict(payload))
        try:
            data = await self._registry.dispatch(command)
        except KeyError:
            return ActionResult(
                success=False,
                error=ActionError(
                    code="action_not_found",
                    message=f"Action {action!r} is not registered",
                    recoverable=False,
                ),
            )
        except Exception as exc:  # noqa: BLE001 — маппим в envelope.
            return ActionResult(
                success=False,
                error=ActionError(
                    code="dispatch_failed",
                    message=str(exc) or exc.__class__.__name__,
                    details={"exception_type": exc.__class__.__name__},
                    recoverable=False,
                ),
            )
        return ActionResult(success=True, data=data)


_default_dispatcher: DefaultActionDispatcher | None = None


def get_action_dispatcher() -> DefaultActionDispatcher:
    """Singleton-доступ к диспетчеру (для DI и DSL processors)."""
    global _default_dispatcher
    if _default_dispatcher is None:
        _default_dispatcher = DefaultActionDispatcher()
    return _default_dispatcher
