"""Async utilities — asyncer-based helpers.

asyncer предоставляет:
- syncify() / asyncify() для bridge между sync и async
- TaskGroup helpers
- Timeout context managers

Fallback на стандартную asyncio если asyncer не установлен.

Usage::

    from src.backend.core.utils.async_utils import run_sync_in_thread, gather_with_timeout

    # Sync function в async контексте
    result = await run_sync_in_thread(heavy_cpu_task, data)

    # Parallel tasks с общим timeout
    results = await gather_with_timeout([task1(), task2()], timeout=30)
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from src.backend.infrastructure.logging.factory import get_logger

__all__ = (
    "async_with_timeout",
    "gather_with_timeout",
    "run_sync_in_thread",
    "task_group_tolerant",
)

logger = get_logger("core.utils.async_utils")

T = TypeVar("T")


try:
    import asyncer

    ASYNCER_AVAILABLE = True
except ImportError:
    ASYNCER_AVAILABLE = False
    asyncer = None


async def run_sync_in_thread(fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    """Выполняет sync функцию в thread pool, не блокируя event loop.

    asyncer.asyncify() preserves signature type-safety; asyncio.to_thread
    — fallback.
    """
    if ASYNCER_AVAILABLE:
        async_fn = asyncer.asyncify(fn)
        return await async_fn(*args, **kwargs)

    import functools

    return await asyncio.to_thread(functools.partial(fn, *args, **kwargs))


async def gather_with_timeout(
    coros: list[Awaitable[T]], *, timeout: float = 30.0, return_exceptions: bool = True
) -> list[T | Exception]:
    """Run tasks in parallel with SHARED timeout.

    Если любая задача превышает timeout, все остальные отменяются.
    При return_exceptions=True возвращает Exception вместо raise.
    """
    try:
        results = await asyncio.wait_for(
            asyncio.gather(*coros, return_exceptions=return_exceptions), timeout=timeout
        )
        return list(results)
    except TimeoutError:
        logger.warning("gather_with_timeout exceeded %ds", timeout)
        raise


async def async_with_timeout(
    coro: Awaitable[T], *, timeout: float, default: T | None = None
) -> T | None:
    """Выполняет coroutine с timeout. При timeout возвращает default."""
    try:
        return await asyncio.wait_for(coro, timeout=timeout)
    except TimeoutError:
        return default


async def task_group_tolerant(coros: list[Awaitable[T]]) -> list[T | BaseException]:
    """asyncio.TaskGroup с tolerant-семантикой (Sprint 9 K3 W8).

    В отличие от ``asyncio.gather(..., return_exceptions=True)`` использует
    современный ``TaskGroup`` API (Python 3.11+):

    * Каждая coroutine получает свой :class:`asyncio.Task`.
    * Внутри TaskGroup исключения собираются tolerant-ом, остальные
      задачи дожидаются.
    * Возвращает гомогенный список результатов или :class:`BaseException`.

    Args:
        coros: список awaitable.

    Returns:
        Список длины ``len(coros)`` — каждая позиция результат либо
        exception в той же позиции.
    """
    results: list[T | BaseException] = [None] * len(coros)  # type: ignore[list-item]

    async def _wrap(idx: int, awaitable: Awaitable[T]) -> None:
        try:
            results[idx] = await awaitable
        except BaseException as exc:
            results[idx] = exc

    async with asyncio.TaskGroup() as tg:
        for i, c in enumerate(coros):
            tg.create_task(_wrap(i, c))

    return results
