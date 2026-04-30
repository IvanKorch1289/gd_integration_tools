"""Унифицированный retry-декоратор поверх ``tenacity`` (Wave 6.3).

API:
    ``@with_retry(policy=RetryPolicy(...))``  — оборачивает coroutine.
    ``RetryPolicy``  — declarative-конфиг (max_attempts, backoff,
    retry_on_exceptions, budget).

Под капотом — ``tenacity.AsyncRetrying`` с exponential backoff + jitter
и опциональным ``RetryBudget`` (token bucket) против retry-storm'ов.
"""

import functools
import logging
from dataclasses import dataclass, field
from typing import Awaitable, Callable, ParamSpec, TypeVar

from tenacity import (
    AsyncRetrying,
    RetryError,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
    wait_random,
)

from src.core.config.constants import consts
from src.infrastructure.resilience.retry_budget import RetryBudget, RetryBudgetExhausted

__all__ = ("RetryPolicy", "with_retry")

logger = logging.getLogger("resilience.retry")

P = ParamSpec("P")
R = TypeVar("R")


@dataclass(slots=True, frozen=True)
class RetryPolicy:
    """Declarative-конфиг retry.

    Дефолты — из ``core.config.constants.consts``.
    """

    max_attempts: int = consts.DEFAULT_RETRY_MAX_ATTEMPTS
    initial_backoff: float = consts.DEFAULT_RETRY_INITIAL_BACKOFF
    backoff_multiplier: float = consts.DEFAULT_RETRY_BACKOFF_MULTIPLIER
    jitter: float = consts.DEFAULT_RETRY_JITTER
    retry_on: tuple[type[BaseException], ...] = (Exception,)
    budget: RetryBudget | None = field(default=None, compare=False)


def with_retry(
    policy: RetryPolicy | None = None,
) -> Callable[[Callable[P, Awaitable[R]]], Callable[P, Awaitable[R]]]:
    """Декоратор для асинхронных функций.

    При исчерпании ``RetryBudget`` повтор пропускается, последняя ошибка
    пробрасывается без задержки. ``RetryError`` оборачивает финальное
    исключение через стандартный tenacity.
    """
    final_policy = policy or RetryPolicy()

    def decorator(func: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
        @functools.wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            budget = final_policy.budget
            if budget is not None:
                await budget.record_attempt()

            retrying = AsyncRetrying(
                stop=stop_after_attempt(final_policy.max_attempts),
                wait=wait_exponential(
                    multiplier=final_policy.initial_backoff,
                    exp_base=final_policy.backoff_multiplier,
                )
                + wait_random(0, final_policy.jitter),
                retry=retry_if_exception_type(final_policy.retry_on),
                reraise=True,
            )
            attempt_no = 0
            try:
                async for attempt in retrying:
                    attempt_no += 1
                    if budget is not None and attempt_no > 1:
                        if not await budget.try_retry():
                            raise RetryBudgetExhausted(budget.name)
                    with attempt:
                        result = await func(*args, **kwargs)
                        return result
            except RetryError as exc:
                logger.debug("Retry exhausted for %s: %s", func.__name__, exc)
                raise
            raise RuntimeError(f"with_retry({func.__name__}) exited without result")

        return wrapper

    return decorator
