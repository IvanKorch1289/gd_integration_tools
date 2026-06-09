"""DI-декораторы для DSL-функций.

Sprint 40 W1.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, TypeVar

from src.backend.dsl.di.container import Container

if TYPE_CHECKING:
    pass

F = TypeVar("F", bound=Callable[..., Any])


def inject(func: F) -> F:
    """Декоратор: автоматически резолвит ``Container.depends()`` параметры.

    Пример::

        @inject
        async def process_order(
            exchange: Exchange[Any],
            context: ExecutionContext,
            db: DatabaseSessionManager = Container.depends(),
        ) -> None:
            ...

    При вызове ``process_order(exchange, context)`` декоратор дополняет
    kwargs недостающими зависимостями через :meth:`Container.resolve_signature`.

    Args:
        func: Функция или coroutine с ``InjectMarker`` defaults.

    Returns:
        Обертка с тем же интерфейсом.
    """
    sig = inspect.signature(func)

    def wrapper(*args: Any, **kwargs: Any) -> Any:
        bound = sig.bind_partial(*args, **kwargs)
        # bound.arguments содержит только явно переданные аргументы

        resolved = Container.resolve_signature(
            func,
            exchange=kwargs.get("exchange") or (args[0] if args else None),
            context=kwargs.get("context") or (args[1] if len(args) > 1 else None),
        )

        for name, value in resolved.items():
            if name not in bound.arguments and value is not inspect.Parameter.empty:
                kwargs[name] = value

        return func(*args, **kwargs)

    # Сохраняем метаданные
    wrapper.__name__ = getattr(func, "__name__", "injected")
    wrapper.__qualname__ = getattr(func, "__qualname__", "")
    wrapper.__wrapped__ = func  # type: ignore[attr-defined]
    wrapper.__inject_markers__ = True  # type: ignore[attr-defined]
    return wrapper  # type: ignore[return-value]
