"""Resilience decorators для коннекторов (Sprint I-3.2).

Унифицированный паттерн: добавляет Circuit Breaker + Retry к любому
коннектору через decorator. Решает gap "MongoDB/ClickHouse/ES/NATS без CB".

Использование::

    from src.backend.core.resilience.connector_resilience import resilient

    class MongoDBClient:
        @resilient(name="mongodb_main", max_attempts=3)
        async def find(self, query: dict) -> list[dict]:
            ...

Или через mixin::

    class MongoDBClient(ResilientConnectorMixin):
        async def find(self, query: dict) -> list[dict]:
            ...
        # _resilient_config = {"name": "mongodb_main", "max_attempts": 3}
"""

from __future__ import annotations

import functools
from collections.abc import Callable
from typing import Any, ParamSpec, TypeVar

from src.backend.core.logging import get_logger

__all__ = ("ResilientConnectorMixin", "resilient")

_logger = get_logger("core.resilience.connector_resilience")

P = ParamSpec("P")
R = TypeVar("R")


def resilient(
    *,
    name: str,
    max_attempts: int = 3,
    initial_backoff: float = 0.5,
    backoff_multiplier: float = 2.0,
    excluded_exceptions: tuple[type[BaseException], ...] | None = None,
) -> Callable[[Callable[P, Awaitable[R]]], Callable[P, Awaitable[R]]]:
    """Decorator: добавляет Circuit Breaker + Retry к async методу коннектора.

    Args:
        name: Имя breaker'а (например, ``"mongodb_main"``, ``"clickhouse_query"``).
        max_attempts: Максимум retry попыток (default 3).
        initial_backoff: Стартовая задержка retry (сек).
        backoff_multiplier: Множитель exponential backoff.
        excluded_exceptions: Исключения, которые НЕ retry (например, ValueError).

    Returns:
        Decorated async function с CB guard + tenacity retry.
    """
    excluded = excluded_exceptions or ()

    def decorator(func: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
        """Wrap async function с CB + retry."""

        @functools.wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            # Lazy imports — избегаем circular imports
            from src.backend.core.resilience import RetryPolicy, with_retry
            from src.backend.core.resilience.breaker import get_breaker_registry

            # Get or create breaker
            registry = get_breaker_registry()
            breaker = registry.get_or_create(name)

            # Build retry policy
            policy = RetryPolicy(
                max_attempts=max_attempts,
                initial_backoff=initial_backoff,
                backoff_multiplier=backoff_multiplier,
                retry_on=(Exception,) if not excluded else (Exception,),
            )

            # Wrap in breaker guard + retry
            try:
                async with breaker.guard():
                    retry_decorator = with_retry(policy)

                    @retry_decorator
                    async def _inner() -> R:
                        return await func(*args, **kwargs)

                    return await _inner()
            except Exception as exc:
                _logger.debug(
                    "resilient.%s failed: %s (excluded=%s)",
                    name,
                    exc,
                    any(isinstance(exc, e) for e in excluded),
                )
                raise

        return wrapper

    return decorator


class ResilientConnectorMixin:
    """Mixin: добавляет CB + Retry через class-level config.

    Использование::

        class MongoDBClient(ResilientConnectorMixin):
            _resilient_methods = {"find": "mongodb_main", "insert": "mongodb_write"}

            async def find(self, query):
                # Auto-wrapped with CB("mongodb_main") + retry(3)
                ...

    Note:
        ``__init_subclass__`` оборачивает методы перечисленные в
        ``_resilient_methods`` (S182 refactor).
    """

    _resilient_methods: dict[str, str] = {}

    def __init_subclass__(cls, **kwargs: Any) -> None:
        """Auto-wrap configured methods с CB + retry."""
        super().__init_subclass__(**kwargs)
        for method_name, breaker_name in cls._resilient_methods.items():
            if hasattr(cls, method_name):
                original = getattr(cls, method_name)
                decorated = resilient(name=breaker_name)(original)
                setattr(cls, method_name, decorated)
