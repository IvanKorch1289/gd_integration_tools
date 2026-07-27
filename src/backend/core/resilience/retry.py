"""Унифицированный retry-декоратор поверх ``tenacity``.

Sprint 1 V16 Single-Entry (Step 3.2): canonical-модуль, в который
переместилась реализация из ``infrastructure/resilience/retry.py``.
Старый модуль остаётся как backward-compat shim (re-export).

API:
    ``@with_retry(policy=RetryPolicy(...))`` — оборачивает coroutine.
    ``RetryPolicy`` — declarative-конфиг (max_attempts, backoff,
    retry_on_exceptions, budget).
    ``Retry`` — alias на ``RetryPolicy`` (каноническое имя, единое с
    ``CircuitBreaker``/``RateLimiter``).

Под капотом — ``tenacity.AsyncRetrying`` с exponential backoff + jitter
и опциональным ``RetryBudget`` (token bucket) против retry-storm'ов.

Сосуществование с ``core/orchestration/retry.py``: тот модуль определяет
Pydantic-``RetryPolicy`` для durable workflow-шагов (с ``compensate``).
Эта семантика отличается и не объединяется автоматически.
"""

from __future__ import annotations

import asyncio
import functools
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from typing import Any, ParamSpec, TypeVar

from tenacity import (
    AsyncRetrying,
    RetryCallState,
    RetryError,
    retry_if_exception_type,
    retry_if_not_exception_type,
    stop_after_attempt,
    wait_exponential,
    wait_random,
)

from src.backend.core.config.constants import consts
from src.backend.core.logging import get_logger
from src.backend.core.resilience.retry_budget import RetryBudget, RetryBudgetExhausted

__all__ = (
    "Retry",
    "RetryBudgetExhausted",
    "RetryPolicy",
    "async_retry",
    "default_retryable",
    "make_async_retry",
    "retry_async",
    "with_retry",
)

logger = get_logger("resilience.retry")

P = ParamSpec("P")
T = TypeVar("T")
R = TypeVar("R")


@dataclass(slots=True, frozen=True)
class RetryPolicy:
    """Declarative-конфиг retry.

    Дефолты — из ``core.config.constants.consts``.
    """

    max_attempts: int = consts.DEFAULT_RETRY_MAX_ATTEMPTS
    initial_backoff: float = consts.DEFAULT_RETRY_INITIAL_BACKOFF
    max_backoff: float = consts.DEFAULT_RETRY_MAX_BACKOFF
    backoff_multiplier: float = consts.DEFAULT_RETRY_BACKOFF_MULTIPLIER
    jitter: float = consts.DEFAULT_RETRY_JITTER
    retry_on: tuple[type[BaseException], ...] = (Exception,)
    budget: RetryBudget | None = field(default=None, compare=False)


# Канонический alias по PLAN.md V16 §3.2.
Retry = RetryPolicy


def with_retry(
    policy: RetryPolicy | None = None,
    *,
    max_attempts: int | None = None,
    initial_backoff: float | None = None,
    max_backoff: float | None = None,
    backoff_multiplier: float | None = None,
    jitter: float | bool | None = None,
    retry_on: tuple[type[BaseException], ...] | None = None,
) -> Callable[[Callable[P, Awaitable[R]]], Callable[P, Awaitable[R]]]:
    """Декоратор для асинхронных функций.

    При исчерпании ``RetryBudget`` повтор пропускается, последняя ошибка
    пробрасывается без задержки. ``RetryError`` оборачивает финальное
    исключение через стандартный tenacity.

    M3: дополнительные kwargs (``max_attempts``, ``initial_backoff``,
    ``max_backoff``, ``backoff_multiplier``, ``jitter``, ``retry_on``)
    позволяют мигрировать sink'и с ``core.resilience.connector_retry`` без
    потери семантики (GCP-style jitter + max_backoff cap). Параметр
    ``jitter`` принимает ``bool`` (``True`` → 0.1s, ``False`` → 0.0s)
    для обратной совместимости с ``connector_retry``.
    """
    overrides: dict[str, Any] = {}
    if max_attempts is not None:
        overrides["max_attempts"] = max_attempts
    if initial_backoff is not None:
        overrides["initial_backoff"] = initial_backoff
    if max_backoff is not None:
        overrides["max_backoff"] = max_backoff
    if backoff_multiplier is not None:
        overrides["backoff_multiplier"] = backoff_multiplier
    if jitter is not None:
        if isinstance(jitter, bool):
            overrides["jitter"] = 0.1 if jitter else 0.0
        else:
            overrides["jitter"] = jitter
    if retry_on is not None:
        overrides["retry_on"] = retry_on
    final_policy: RetryPolicy = (
        policy
        if policy is not None and not overrides
        else replace(policy or RetryPolicy(), **overrides)
    )

    def decorator(func: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
        """Decorator that adds retry logic to async functions.

        Args:
            func: Async function to wrap with retry logic.

        Returns:
            Wrapped function with retry capability.
        """

        @functools.wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            """Wrapper that implements retry logic with budget tracking."""
            budget = final_policy.budget
            if budget is not None:
                await budget.record_attempt()

            effective_retry = retry_if_exception_type(final_policy.retry_on)
            effective_retry = effective_retry & retry_if_not_exception_type(
                RetryBudgetExhausted
            )
            retrying = AsyncRetrying(
                stop=stop_after_attempt(final_policy.max_attempts),
                wait=wait_exponential(
                    multiplier=final_policy.initial_backoff,
                    max=final_policy.max_backoff,
                    exp_base=final_policy.backoff_multiplier,
                )
                + wait_random(0, final_policy.jitter),
                retry=effective_retry,
                reraise=True,
            )
            attempt_no = 0
            try:
                async for attempt in retrying:
                    attempt_no += 1
                    with attempt:
                        if budget is not None and attempt_no > 1:
                            if not await budget.try_retry():
                                raise RetryBudgetExhausted(budget.name)
                        result = await func(*args, **kwargs)
                        return result
            except RetryError as exc:
                logger.debug("Retry exhausted for %s: %s", func.__name__, exc)
                raise
            raise RuntimeError(f"with_retry({func.__name__}) exited without result")

        return wrapper

    return decorator


def default_retryable() -> tuple[type[BaseException], ...]:
    """Return the default transient exception types for async operations."""
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
    """Run an async callable with exponential-backoff retries."""
    retry_types = retryable or default_retryable()
    call_kwargs = kwargs or {}

    try:
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(max_attempts),
            wait=wait_exponential(multiplier=base_delay, max=max_delay),
            retry=retry_if_exception_type(retry_types),
            reraise=True,
        ):
            with attempt:
                if attempt.retry_state.attempt_number > 1:
                    logger.warning(
                        "retry op=%s attempt=%d/%d",
                        op or "?",
                        attempt.retry_state.attempt_number,
                        max_attempts,
                    )
                return await coro_fn(*args, **call_kwargs)
    except RetryError as exc:
        final_exception = exc.last_attempt.exception() if exc.last_attempt else None
        if final_exception is not None:
            raise final_exception from None
        raise
    raise RuntimeError("retry_async exited without result")


def make_async_retry(
    *,
    max_attempts: int = 3,
    initial_backoff: float = 1.0,
    multiplier: float = 2.0,
    max_backoff: float = 30.0,
    on: tuple[type[BaseException], ...] = (Exception,),
) -> Callable[[Callable[P, Awaitable[R]]], Callable[P, Awaitable[R]]]:
    """Create an async tenacity retry decorator for legacy call sites."""

    def decorator(fn: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
        @functools.wraps(fn)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            retrying = AsyncRetrying(
                stop=stop_after_attempt(max_attempts),
                wait=wait_exponential(
                    multiplier=initial_backoff,
                    exp_base=multiplier,
                    max=max_backoff,
                ),
                retry=retry_if_exception_type(on),
                reraise=True,
                before_sleep=_log_before_sleep(fn.__name__),
            )
            async for attempt in retrying:
                with attempt:
                    return await fn(*args, **kwargs)
            raise RuntimeError(
                f"make_async_retry: {fn.__name__} exited without result"
            )

        return wrapper

    return decorator


def _log_before_sleep(fn_name: str) -> Callable[[RetryCallState], None]:
    """Build the debug callback used by :func:`make_async_retry`."""

    def callback(retry_state: RetryCallState) -> None:
        exc = retry_state.outcome.exception() if retry_state.outcome else None
        logger.debug(
            "retry attempt=%d fn=%s exc=%r next_sleep=%.2fs",
            retry_state.attempt_number,
            fn_name,
            exc,
            retry_state.next_action.sleep if retry_state.next_action else 0,
        )

    return callback


async_retry = make_async_retry()
