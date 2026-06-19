"""Единый async-retry фасад поверх tenacity (K3 W1: tenacity unification).

Предоставляет фабрику ``make_async_retry`` и декоратор ``async_retry`` для
замены разрозненных custom retry-loop'ов на единый стек tenacity 9.0+.

Архитектура:
    * ``make_async_retry`` — фабрика декораторов с конфигурируемыми
      параметрами (max_attempts, initial_backoff, multiplier, on);
    * ``async_retry`` — готовый декоратор с дефолтами (3 попытки,
      exponential 1s → 8s, retry на любое Exception);
    * Логирование каждой попытки через ``structlog``-compatible logger
      ``resilience.retry``; детали в DEBUG, финальный провал в WARNING.

Сосуществование с ``core/resilience/retry.py``:
    Модуль ``core/resilience/retry.py`` определяет ``with_retry``
    + ``RetryPolicy`` (dataclass) для use-cases с ``RetryBudget``.
    Этот модуль — облегчённый фасад для callsites без budget'а.

Использование:
    from src.backend.infrastructure.resilience.retry import make_async_retry

    send = make_async_retry(max_attempts=3, initial_backoff=1.0, on=(IOError,))(
        my_async_fn
    )

    # Или как декоратор:
    @make_async_retry(max_attempts=5)
    async def fetch_data() -> bytes: ...
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import ParamSpec

# S168 W11 P2-2: PEP 695 type alias для R (TypeVar → type alias).
# P (ParamSpec) остаётся ParamSpec — нет PEP 695 эквивалента для ParamSpec.
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from src.backend.infrastructure.logging.factory import get_logger

__all__ = ("async_retry", "make_async_retry")

logger = get_logger("resilience.retry")

# S168 W11 P2-2: PEP 695 type alias (replaces TypeVar("R")).
# Используем TypeAliasType (backward-compat with 3.12+; в 3.14 можно
# использовать ``type R = object`` syntax, но он не работает если
# ParamSpec() присваивание идёт в том же блоке).
from typing import TypeAliasType

P = ParamSpec("P")
R = TypeAliasType("R", object)


def make_async_retry(
    *,
    max_attempts: int = 3,
    initial_backoff: float = 1.0,
    multiplier: float = 2.0,
    max_backoff: float = 30.0,
    on: tuple[type[BaseException], ...] = (Exception,),
) -> Callable[[Callable[P, Awaitable[R]]], Callable[P, Awaitable[R]]]:
    """Фабрика декоратора async-retry поверх tenacity.

    Args:
        max_attempts: Максимальное число попыток (включая первую).
        initial_backoff: Начальная задержка в секундах между попытками.
        multiplier: Множитель exponential backoff (каждая следующая задержка
            умножается на ``multiplier``).
        max_backoff: Верхняя граница задержки между попытками в секундах.
        on: Кортеж исключений, при которых выполняется retry. По умолчанию —
            любое ``Exception``.

    Returns:
        Декоратор для async-функции: оборачивает её в tenacity AsyncRetrying
        с заданными параметрами. Финальное исключение пробрасывается через
        ``reraise=True``.

    Пример::

        @make_async_retry(max_attempts=5, initial_backoff=0.5, on=(TimeoutError,))
        async def call_external_api() -> dict: ...
    """

    def decorator(fn: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
        import functools

        @functools.wraps(fn)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            retrying = AsyncRetrying(
                stop=stop_after_attempt(max_attempts),
                wait=wait_exponential(
                    multiplier=initial_backoff, exp_base=multiplier, max=max_backoff
                ),
                retry=retry_if_exception_type(on),
                reraise=True,
                before_sleep=_log_before_sleep(fn.__name__),
            )
            async for attempt in retrying:
                with attempt:
                    return await fn(*args, **kwargs)
            # Tenacity с reraise=True бросит исключение до этой строки;
            # ветка недостижима, нужна только для mypy.
            raise RuntimeError(
                f"make_async_retry: {fn.__name__} exited without result"
            )  # pragma: no cover

        return wrapper

    return decorator


def _log_before_sleep(fn_name: str):
    """Возвращает tenacity before_sleep callback с логированием попытки.

    Args:
        fn_name: Имя оборачиваемой функции для контекста в логах.
    """
    from tenacity import RetryCallState

    def _callback(retry_state: RetryCallState) -> None:
        exc = retry_state.outcome.exception() if retry_state.outcome else None
        logger.debug(
            "retry attempt=%d fn=%s exc=%r next_sleep=%.2fs",
            retry_state.attempt_number,
            fn_name,
            exc,
            retry_state.next_action.sleep if retry_state.next_action else 0,
        )

    return _callback


# Готовый декоратор с дефолтами — для простых callsites без кастомизации.
async_retry = make_async_retry()
