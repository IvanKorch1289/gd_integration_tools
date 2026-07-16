"""Connector retry decorator (Security Wave S4).

Унифицированный ``@with_retry`` для всех 39 connectors. Exponential backoff
+ jitter настраиваются per-connector. Тонкая обёртка над
:class:`tenacity.AsyncRetrying` + :func:`tenacity.wait_exponential_jitter`
(GCP-style: ``min(initial * 2**n + uniform(0, jitter), max)``).

Defaults:
    * ``max_attempts=3``
    * ``initial_backoff=1.0s``
    * ``max_backoff=10.0s``
    * ``backoff_multiplier=2.0``
    * ``jitter=0.1`` (10% амплитуды — prevent thundering herd)
    * ``retry_on=(ConnectionError, TimeoutError, OSError)``

Применяется в :mod:`src.backend.infrastructure.sinks` для всех
publish/send методов, где нет своего retry-loop'а.

Usage::

    class MqttSink:
        @with_retry(max_attempts=5, retry_on=(ConnectionError,))
        async def publish(self, payload):
            ...

Декоратор корректно работает под ``@with_breaker`` (ставьте ``@with_retry``
**ниже** — ближе к функции — чтобы CB видел все попытки retry).
"""

from __future__ import annotations

import functools
from collections.abc import Awaitable, Callable
from typing import ParamSpec, TypeVar

from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from src.backend.core.logging import get_logger

__all__ = ("with_retry",)


_P = ParamSpec("_P")
_R = TypeVar("_R")

# Узкий набор transient-исключений. ValueError, KeyError и подобные
# «логические» ошибки не ретраятся.
_DEFAULT_RETRY_ON: tuple[type[BaseException], ...] = (
    ConnectionError,
    TimeoutError,
    OSError,
)

# Амплитуда jitter в абсолютных единицах (секунды). Передаётся как
# ``jitter=0.1`` в ``wait_exponential_jitter`` — см. формулу в docstring.
_DEFAULT_JITTER = 0.1

_logger = get_logger(__name__)


def with_retry(
    *,
    max_attempts: int = 3,
    initial_backoff: float = 1.0,
    max_backoff: float = 10.0,
    backoff_multiplier: float = 2.0,
    jitter: float | bool = True,
    retry_on: tuple[type[BaseException], ...] = _DEFAULT_RETRY_ON,
) -> Callable[[Callable[_P, Awaitable[_R]]], Callable[_P, Awaitable[_R]]]:
    """Per-connector retry decorator.

    Args:
        max_attempts: Общее число попыток (включая первую). Default ``3``.
        initial_backoff: Начальная задержка в секундах. Default ``1.0``.
        max_backoff: Максимальная задержка (cap) в секундах. Default ``10.0``.
        backoff_multiplier: Множитель exponential backoff. Default ``2.0``.
        jitter: Либо ``bool`` (True → 0.1s, False → 0.0s), либо
            ``float`` — амплитуда jitter в секундах для
            ``wait_exponential_jitter``. Default ``True``.
        retry_on: Tuple exception types, при которых выполняется retry.
            Default — transient I/O (``ConnectionError``, ``TimeoutError``,
            ``OSError``).

    Returns:
        Декоратор, оборачивающий async-функцию. Совместим с композицией
        поверх ``@with_breaker`` / ``@resilient``.
    """
    if isinstance(jitter, bool):
        jitter_value: float = _DEFAULT_JITTER if jitter else 0.0
    else:
        jitter_value = jitter

    def decorator(
        func: Callable[_P, Awaitable[_R]],
    ) -> Callable[_P, Awaitable[_R]]:
        @functools.wraps(func)
        async def wrapper(*args: _P.args, **kwargs: _P.kwargs) -> _R:
            retrying = AsyncRetrying(
                stop=stop_after_attempt(max_attempts),
                wait=wait_exponential_jitter(
                    initial=initial_backoff,
                    max=max_backoff,
                    exp_base=backoff_multiplier,
                    jitter=jitter_value,
                ),
                retry=retry_if_exception_type(retry_on),
                reraise=True,
            )
            try:
                async for attempt in retrying:
                    with attempt:
                        return await func(*args, **kwargs)
            except Exception as exc:
                _logger.debug(
                    "with_retry: %s exhausted after %d attempts: %s",
                    func.__name__,
                    max_attempts,
                    exc,
                )
                raise
            # tenacity с reraise=True бросит исключение до этой строки;
            # ветка недостижима, нужна только для mypy.
            raise RuntimeError(  # pragma: no cover
                f"with_retry({func.__name__}) exited without result"
            )

        return wrapper

    return decorator
