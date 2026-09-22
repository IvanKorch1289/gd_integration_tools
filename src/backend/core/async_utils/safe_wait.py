"""Safe ``asyncio.wait_for`` helper (Sprint 3 — audit 2026-09-22 P1).

Аудит finding: 17 ``asyncio.wait_for()`` calls без try/except nearby.
Этот helper предоставляет cancel-friendly pattern:

1. ``safe_wait_for`` — обёртка с default cancellation policy.
2. ``with_timeout`` — context manager с cancel-friendly cleanup.
3. ``cancel_on_timeout`` — decorator для async функций.

Cancel-friendly semantics:
- TimeoutError ловится явно и re-raises с дополнительным context.
- CancelledError НЕ проглатывается (должен прокидываться до caller).

Использование::

    from src.backend.core.async_utils.safe_wait import safe_wait_for

    result = await safe_wait_for(some_coro(), timeout=5.0)
"""

from __future__ import annotations

import asyncio
import contextlib
import functools
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


class TimeoutWithContext(asyncio.TimeoutError):
    """TimeoutError с дополнительным context для diagnostics."""

    def __init__(self, message: str, *, timeout: float, coro_name: str) -> None:
        """Инициализация.

        Args:
            message: человеко-читаемое сообщение.
            timeout: timeout в секундах.
            coro_name: имя coroutine которая timed out.
        """
        super().__init__(message)
        self.timeout = timeout
        self.coro_name = coro_name


async def safe_wait_for(
    awaitable: Awaitable[T],
    timeout: float,
    *,
    operation: str | None = None,
    reraise: bool = True,
) -> T | None:
    """Cancel-friendly asyncio.wait_for wrapper.

    Args:
        awaitable: coroutine или future.
        timeout: timeout в секундах.
        operation: имя операции для diagnostics.
        reraise: True (default) → raise TimeoutWithContext. False → return None.

    Returns:
        Result of awaitable или None (если reraise=False).

    Raises:
        TimeoutWithContext: timeout exceeded (если reraise=True).
        asyncio.CancelledError: внешний cancel — прокидывается всегда.
    """
    if operation is None:
        operation = getattr(awaitable, "__name__", "unknown")
    try:
        return await asyncio.wait_for(awaitable, timeout=timeout)
    except asyncio.TimeoutError as exc:
        if reraise:
            raise TimeoutWithContext(
                f"Operation '{operation}' exceeded {timeout}s timeout",
                timeout=timeout,
                coro_name=operation,
            ) from exc
        return None


@contextlib.asynccontextmanager
async def with_timeout(
    coro_factory: Callable[[], Awaitable[T]],
    timeout: float,
    *,
    operation: str | None = None,
) -> AsyncIterator[T]:
    """Context manager with cancel-friendly timeout.

    Args:
        coro_factory: callable, возвращающая fresh coroutine.
        timeout: timeout в секундах.
        operation: имя операции для diagnostics.

    Yields:
        Result of awaitable.
    """
    if operation is None:
        operation = getattr(coro_factory, "__name__", "with_timeout")
    awaitable = coro_factory()
    try:
        result = await asyncio.wait_for(awaitable, timeout=timeout)
        yield result
    except asyncio.TimeoutError as exc:
        raise TimeoutWithContext(
            f"Context '{operation}' exceeded {timeout}s timeout",
            timeout=timeout,
            coro_name=operation,
        ) from exc


def cancel_on_timeout(
    timeout: float, *, operation: str | None = None
) -> Callable[[Callable[..., Awaitable[Any]]], Callable[..., Awaitable[Any]]]:
    """Decorator для async функций с timeout + cancellation."""

    def decorator(func: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
        op_name = operation or func.__name__

        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            return await safe_wait_for(
                func(*args, **kwargs), timeout=timeout, operation=op_name
            )

        return wrapper

    return decorator


__all__ = ("TimeoutWithContext", "cancel_on_timeout", "safe_wait_for", "with_timeout")
