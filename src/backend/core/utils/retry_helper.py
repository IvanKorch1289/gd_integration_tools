"""RetryPolicyHelper (S171 M5 — централизация tenacity-style retry).

Единый wrapper для retry-логики. Заменяет:
- src/backend/infrastructure/clients/transport/http/request_mixin.py:76 (http retry)
- src/backend/infrastructure/clients/storage/clickhouse.py:193 (clickhouse retry)
- другие manual ``for attempt in range(max)`` loops

Pattern (Ponytail, D140): thin wrapper, no decorators.
Использует :func:`tenacity.AsyncRetrying` под капотом.
"""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from src.backend.core.logging import get_logger

_logger = get_logger(__name__)

T = TypeVar("T")

__all__ = ("retry_async", "default_retryable")


def default_retryable() -> tuple[type[BaseException], ...]:
    """Default tuple of retryable exception types."""
    return (ConnectionError, OSError, asyncio.TimeoutError)


async def retry_async(
    coro_fn: Callable[..., Awaitable[T]],
    *,
    max_attempts: int = 3,
    base_delay: float = 0.5,
    max_delay: float = 10.0,
    retryable: tuple[type[BaseException], ...] | None = None,
    op: str | None = None,
    args: tuple[Any, ...] = (),
    kwargs: dict[str, Any] | None = None,
) -> T:
    """Run ``coro_fn`` с exponential backoff retry.

    Args:
        coro_fn: Async function для retry.
        max_attempts: Сколько раз пытаться (default 3).
        base_delay: Начальная задержка (default 0.5s).
        max_delay: Максимальная задержка (default 10s).
        retryable: Tuple of exception types для retry. Default — network errors.
        op: Имя операции (для логирования).
        args: Positional args для coro_fn.
        kwargs: Keyword args для coro_fn.

    Returns:
        Результат coro_fn.

    Raises:
        Last exception if all attempts failed.
    """
    from tenacity import (
        AsyncRetrying,
        RetryError,
        retry_if_exception_type,
        stop_after_attempt,
        wait_exponential,
    )

    retry_types = retryable or default_retryable()
    kwargs = kwargs or {}

    try:
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(max_attempts),
            wait=wait_exponential(multiplier=base_delay, max=max_delay),
            retry=retry_if_exception_type(retry_types),
            reraise=True,
        ):
            with attempt:
                if attempt.retry_state.attempt_number > 1:
                    _logger.warning(
                        "retry op=%s attempt=%d/%d",
                        op or "?",
                        attempt.retry_state.attempt_number,
                        max_attempts,
                    )
                return await coro_fn(*args, **kwargs)
    except RetryError as exc:
        # reraise=True means the original exception is wrapped in RetryError.last_attempt
        if exc.last_attempt and exc.last_attempt.exception():
            raise exc.last_attempt.exception() from None
        raise
