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
import logging
from typing import Any, Awaitable, Callable, TypeVar

__all__ = ("run_sync_in_thread", "gather_with_timeout", "async_with_timeout")

logger = logging.getLogger("core.utils.async_utils")

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
    except asyncio.TimeoutError:
        logger.warning("gather_with_timeout exceeded %ds", timeout)
        raise


async def async_with_timeout(
    coro: Awaitable[T], *, timeout: float, default: T | None = None
) -> T | None:
    """Выполняет coroutine с timeout. При timeout возвращает default."""
    try:
        return await asyncio.wait_for(coro, timeout=timeout)
    except asyncio.TimeoutError:
        return default
