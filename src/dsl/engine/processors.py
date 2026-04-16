import inspect
from abc import ABC, abstractmethod
from typing import Any, Awaitable, Callable

from app.dsl.engine.context import ExecutionContext
from app.dsl.engine.exchange import Exchange
from app.schemas.invocation import ActionCommandSchema

__all__ = (
    "ProcessorCallable",
    "BaseProcessor",
    "CallableProcessor",
    "SetHeaderProcessor",
    "SetPropertyProcessor",
    "DispatchActionProcessor",
)

ProcessorCallable = Callable[[Exchange[Any], ExecutionContext], Any | Awaitable[Any]]


class BaseProcessor(ABC):
    """
    Базовый класс для всех DSL-процессоров.

    Каждый процессор получает Exchange и ExecutionContext,
    может модифицировать сообщение, runtime-состояние и результат.
    """

    def __init__(self, name: str | None = None) -> None:
        self.name = name or self.__class__.__name__

    @abstractmethod
    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """
        Выполняет обработку Exchange.

        Args:
            exchange: Текущий Exchange.
            context: Контекст выполнения маршрута.
        """


class CallableProcessor(BaseProcessor):
    """
    Адаптер, превращающий обычную функцию или coroutine в процессор.
    """

    def __init__(self, func: ProcessorCallable, name: str | None = None) -> None:
        super().__init__(name=name or getattr(func, "__name__", None))
        self._func = func

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        result = self._func(exchange, context)
        if inspect.isawaitable(result):
            await result


class SetHeaderProcessor(BaseProcessor):
    """
    Процессор для установки заголовка входного сообщения.
    """

    def __init__(self, key: str, value: Any) -> None:
        super().__init__(name=f"set_header:{key}")
        self.key = key
        self.value = value

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        exchange.in_message.set_header(self.key, self.value)


class SetPropertyProcessor(BaseProcessor):
    """
    Процессор для установки runtime-свойства Exchange.
    """

    def __init__(self, key: str, value: Any) -> None:
        super().__init__(name=f"set_property:{key}")
        self.key = key
        self.value = value

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        exchange.set_property(self.key, self.value)


class DispatchActionProcessor(BaseProcessor):
    """
    Процессор, который преобразует Exchange в ActionCommandSchema
    и исполняет команду через ActionHandlerRegistry.

    Это первый practical bridge между новым DSL и существующей
    action-командной моделью приложения.
    """

    def __init__(
        self,
        action: str,
        *,
        payload_factory: Callable[[Exchange[Any]], dict[str, Any]] | None = None,
        result_property: str = "action_result",
    ) -> None:
        super().__init__(name=f"dispatch_action:{action}")
        self.action = action
        self.payload_factory = payload_factory
        self.result_property = result_property

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        if self.payload_factory is not None:
            payload = self.payload_factory(exchange)
        else:
            body = exchange.in_message.body
            payload = body if isinstance(body, dict) else {}

        command = ActionCommandSchema(action=self.action, payload=payload)

        result = await context.action_registry.dispatch(command)

        exchange.set_property(self.result_property, result)
        exchange.set_out(body=result, headers=dict(exchange.in_message.headers))
