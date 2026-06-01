"""Композитный декоратор ``@policy`` (ADR-0052).

Wave [s1/k2-2-policy-decorator]: единая точка для одновременного применения
четырёх resilience-патернов к async-функции:

* ``cache`` — кеш ответа (короткое замыкание на hit);
* ``rate_limit`` — token-bucket лимиты на rate calls;
* ``circuit_breaker`` — изоляция от каскадных отказов;
* ``retry`` — экспоненциальный backoff с jitter.

Канонический порядок (outer → inner): ``cache → rate_limit → circuit_breaker
→ retry → fn``. Обоснование — см. ADR-0052.

Usage::

    @policy(circuit_breaker="bki_api", retry="default", cache={"ttl": 60, "key": "bki:{0}"})
    async def fetch_bki(client_id: int) -> dict:
        ...
"""

from __future__ import annotations

from functools import wraps
from typing import Any, Awaitable, Callable, Mapping

from src.backend.core.resilience.breaker import (
    Breaker,
    BreakerSpec,
    get_breaker_registry,
)
from src.backend.core.resilience.cache_decorators import cached
from src.backend.core.resilience.rate_limiter import RateLimit, RateLimiter
from src.backend.core.resilience.retry import RetryPolicy, with_retry

__all__ = ("policy",)


def policy(
    *,
    circuit_breaker: str | BreakerSpec | Breaker | None = None,
    rate_limit: RateLimit | None = None,
    retry: RetryPolicy | None = None,
    cache: Mapping[str, Any] | None = None,
) -> Callable[[Callable[..., Awaitable[Any]]], Callable[..., Awaitable[Any]]]:
    """Композитный декоратор resilience.

    Args:
        circuit_breaker: ``str`` (имя breaker'а в registry), ``BreakerSpec``
            (создать новый) или готовый :class:`Breaker`. ``None`` — без CB.
        rate_limit: :class:`RateLimit` спецификация (тарифы). ``None`` — без RL.
        retry: :class:`RetryPolicy`. ``None`` — без retry.
        cache: ``{"ttl": int, "key": str, "backend": str}`` для ``@cached``.
            ``None`` — без кеша.

    Returns:
        Декоратор для async-функции. Композиция в порядке
        ``cache(rl(cb(retry(fn))))``.
    """

    # Eager validation of circuit_breaker type to fail fast.
    if circuit_breaker is not None and not isinstance(
        circuit_breaker, (str, BreakerSpec, Breaker)
    ):
        raise TypeError(
            f"Unsupported circuit_breaker spec: {type(circuit_breaker).__name__}"
        )

    def decorator(func: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
        breaker = _resolve_breaker(circuit_breaker, func=func)
        wrapped: Callable[..., Awaitable[Any]] = func
        if retry is not None:
            wrapped = _wrap_retry(wrapped, retry)
        if breaker is not None:
            wrapped = _wrap_breaker(wrapped, breaker)
        if rate_limit is not None:
            wrapped = _wrap_rate_limit(wrapped, rate_limit)
        if cache is not None:
            cache_kwargs = dict(cache)
            wrapped = cached(
                ttl=cache_kwargs.pop("ttl"),
                key=cache_kwargs.pop("key"),
                backend=cache_kwargs.pop("backend", "multi"),
            )(wrapped)
        return _preserve_signature(func, wrapped)

    return decorator


def _resolve_breaker(
    spec: str | BreakerSpec | Breaker | None,
    func: Callable[..., Awaitable[Any]] | None = None,
) -> Breaker | None:
    if spec is None:
        return None
    if isinstance(spec, Breaker):
        return spec
    registry = get_breaker_registry()
    if isinstance(spec, str):
        existing = registry.get(spec)
        if existing is None:
            return registry.get_or_create(spec, None)
        return existing
    if isinstance(spec, BreakerSpec):
        name = spec.name
        if name == "default" and func is not None:
            name = f"{func.__module__}.{func.__qualname__}"
        return registry.get_or_create(name, spec)
    raise TypeError(f"Unsupported circuit_breaker spec: {type(spec).__name__}")


def _wrap_retry(
    func: Callable[..., Awaitable[Any]], retry: RetryPolicy
) -> Callable[..., Awaitable[Any]]:
    """Применяет :func:`with_retry` (декоратор) к ``func``.

    :func:`with_retry` возвращает новый wrapper при единственном применении —
    переиспользуем его на каждом вызове.
    """
    retried = with_retry(retry)(func)

    @wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        return await retried(*args, **kwargs)

    return wrapper


def _wrap_breaker(
    func: Callable[..., Awaitable[Any]], breaker: Breaker
) -> Callable[..., Awaitable[Any]]:
    @wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        async with breaker.guard():
            return await func(*args, **kwargs)

    return wrapper


def _wrap_rate_limit(
    func: Callable[..., Awaitable[Any]], rate: RateLimit
) -> Callable[..., Awaitable[Any]]:
    """Оборачивает функцию в rate-limit check через canonical Protocol.

    Identifier по умолчанию — ``func.__qualname__``. При превышении
    лимита :class:`RateLimitExceeded` пробрасывается наверх (НЕ ловится
    breaker'ом, см. ADR-0052).
    """
    identifier = func.__qualname__

    @wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        limiter: RateLimiter = _get_limiter()
        await limiter.check(identifier, rate)
        return await func(*args, **kwargs)

    return wrapper


def _get_limiter() -> RateLimiter:
    from src.backend.core.resilience.rate_limiter import get_rate_limiter

    return get_rate_limiter()


def _preserve_signature(
    original: Callable[..., Awaitable[Any]], wrapped: Callable[..., Awaitable[Any]]
) -> Callable[..., Awaitable[Any]]:
    @wraps(original)
    async def adapter(*args: Any, **kwargs: Any) -> Any:
        return await wrapped(*args, **kwargs)

    return adapter
