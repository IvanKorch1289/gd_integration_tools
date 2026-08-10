"""Connector circuit breaker decorator (Security Wave S3).

Унифицированный per-connector Circuit Breaker. Применяется ко всем 39 connectors
(sources/sinks/storage). Использует purgatory как backend через BreakerRegistry.

State:
- closed: normal operation
- open: all requests fail-fast (no upstream call)
- half_open: probe with one request; success → closed, fail → open

Usage::

    class HttpSink:
        @with_breaker("http_sink", failure_threshold=5, recovery_seconds=30)
        async def send(self, payload):
            ...
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from functools import wraps
from typing import ParamSpec, TypeVar

from src.backend.core.resilience.breaker import (
    BreakerSpec,
    CircuitOpen,
    get_breaker_registry,
)

__all__ = ("CircuitOpen", "with_breaker")

_P = ParamSpec("_P")
_R = TypeVar("_R")


def with_breaker(
    name: str,
    *,
    failure_threshold: int = 5,
    recovery_seconds: float = 30.0,
) -> Callable[
    [Callable[_P, Awaitable[_R]]],
    Callable[_P, Awaitable[_R]],
]:
    """Per-connector circuit breaker decorator.

    Args:
        name: Имя breaker'а (например ``"http_sink_main"`` или ``"kafka_consumer"``).
        failure_threshold: Число failures для перехода в ``open``.
        recovery_seconds: Время до повторной попытки (``half_open``).

    """
    spec = BreakerSpec(
        name=name,
        failure_threshold=failure_threshold,
        recovery_timeout=recovery_seconds,
    )
    registry = get_breaker_registry()
    breaker = registry.get_or_create(name, spec)

    def decorator(
        func: Callable[_P, Awaitable[_R]],
    ) -> Callable[_P, Awaitable[_R]]:
        @wraps(func)
        async def wrapper(*args: _P.args, **kwargs: _P.kwargs) -> _R:
            async with breaker.guard():
                return await func(*args, **kwargs)

        return wrapper

    return decorator
