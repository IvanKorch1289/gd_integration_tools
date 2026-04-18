import inspect
from abc import ABC, abstractmethod
from typing import Any, Awaitable, Callable

from app.dsl.engine.context import ExecutionContext
from app.dsl.engine.exchange import Exchange

__all__ = ("ProcessorCallable", "BaseProcessor", "CallableProcessor")

ProcessorCallable = Callable[[Exchange[Any], ExecutionContext], Any | Awaitable[Any]]


class BaseProcessor(ABC):
    """Базовый класс для всех DSL-процессоров."""

    def __init__(self, name: str | None = None) -> None:
        self.name = name or self.__class__.__name__

    @abstractmethod
    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None: ...


class CallableProcessor(BaseProcessor):
    """Адаптер, превращающий обычную функцию или coroutine в процессор."""

    def __init__(self, func: ProcessorCallable, name: str | None = None) -> None:
        super().__init__(name=name or getattr(func, "__name__", None))
        self._func = func

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        result = self._func(exchange, context)
        if inspect.isawaitable(result):
            await result
