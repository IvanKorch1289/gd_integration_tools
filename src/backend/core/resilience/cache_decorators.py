"""Публичный API кеширующих декораторов (``@cached`` / ``@invalidate`` / ``@multi_cached``).

Wave [s1/k2-1-cache-decorator]: тонкий фасад над
:class:`infrastructure.decorators.caching.CachingDecorator`. См. ADR-0051
о причинах отказа от ``aiocache`` в пользу in-house декоратора.

API намеренно компактный:

* ``@cached(ttl=60, key="foo:{args[0]}")`` — обернуть async-функцию;
* ``@invalidate("foo:*")`` — invalidate-pattern-декоратор для mutating-функций;
* ``@multi_cached({"L1": 60, "L2": 600})`` — несколько slots с разными TTL.

Lazy-import :mod:`infrastructure.decorators.caching` — core/ не имеет права
зависеть от infrastructure статически (см. ADR-001 layers). Это decoration-
time resolve, поэтому performance-cost ничтожен.

ИЕРАРХИЯ КЭШИРОВАНИЯ:
  @cached / @multi_cached (этот файл)
     ↓ lazy import
  infrastructure/decorators/caching/decorator.py (CachingDecorator)
     ↓ lazy import
  infrastructure/clients/storage/redis.py (redis_client)

Вызывающий код использует ТОЛЬКО @cached / @multi_cached или кастомный key.
Прямой импорт CachingDecorator из infrastructure запрещён из сервисов.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from functools import wraps
from typing import Any, Literal

from src.backend.core.logging import get_logger
from src.backend.core.utils.cache_keys import build_cache_key

__all__ = ("cached", "invalidate", "multi_cached")

_logger = get_logger(__name__)


Backend = Literal["redis", "memory", "disk", "multi"]


def _build_underlying(*, ttl: int, key_prefix: str, backend: Backend) -> Any:
    """Lazy-конструктор :class:`CachingDecorator` с фиксированным backend-режимом."""
    from src.backend.core.di.providers.infrastructure_facade import (
        get_caching_decorator_class as _get_cd_cls,
    )
    CachingDecorator = _get_cd_cls()

    if backend == "redis":
        use_memory = False
        use_disk = False
    elif backend == "memory":
        use_memory = True
        use_disk = False
    elif backend == "disk":
        use_memory = False
        use_disk = True
    else:  # multi
        use_memory = True
        use_disk = False
    return CachingDecorator(
        expire=ttl,
        key_prefix=key_prefix,
        use_memory_fallback=use_memory,
        use_disk_fallback=use_disk,
    )


def _format_key(template: str, args: tuple, kwargs: dict) -> str:
    """Рендерит key-template через ``str.format(*args, **kwargs)``.

    Поддерживаются placeholder'ы вида ``{args[0]}``, ``{kwargs[user_id]}``,
    ``{0}`` (позиционный), ``{user_id}`` (kwarg).
    """
    try:
        return template.format(*args, args=args, kwargs=kwargs, **kwargs)
    except (IndexError, KeyError) as exc:
        raise ValueError(f"Не удалось отрендерить ключ {template!r}: {exc}") from exc


def cached(
    *, ttl: int, key: str | Callable[..., str], backend: Backend = "multi"
) -> Callable[[Callable[..., Awaitable[Any]]], Callable[..., Awaitable[Any]]]:
    """Декоратор: кеширует результат async-функции на ``ttl`` секунд.

    Args:
        ttl: Время жизни записи в секундах.
        key: Шаблон ключа (``"bki:{args[0]}"``) или callable, возвращающий ключ.
        backend: ``redis`` / ``memory`` / ``disk`` / ``multi`` (Redis+Memory).

    Returns:
        Декоратор для async-функции.
    """

    def decorator(func: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
        """Decorator that caches async function results.

        Args:
            func: Async function to cache.

        Returns:
            Cached version of the function.
        """
        if not asyncio.iscoroutinefunction(func):
            raise TypeError("@cached поддерживает только async-функции")

        if callable(key):
            key_builder = key
        else:

            def key_builder(*args: Any, **kwargs: Any) -> str:
                return _format_key(key, args, kwargs)

        # Подготавливаем underlying CachingDecorator с custom key_builder.
        def _underlying_key(
            _func: Any, args: tuple[Any, ...], kwargs: dict[str, Any]
        ) -> str:
            return key_builder(*args, **kwargs)

        from src.backend.core.di.providers.infrastructure_facade import (
            get_caching_decorator_class as _get_cd_cls2,
        )
        CachingDecorator = _get_cd_cls2()

        decorator_instance = CachingDecorator(
            expire=ttl,
            key_prefix="",  # ключ уже полный из template
            key_builder=_underlying_key,
            use_memory_fallback=(backend in ("memory", "multi")),
            use_disk_fallback=(backend == "disk"),
        )
        wrapped = decorator_instance(func)

        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            return await wrapped(*args, **kwargs)

        # Прикрепляем underlying для invalidation API.
        wrapper.cache = decorator_instance  # type: ignore[attr-defined]
        return wrapper

    return decorator


def invalidate(
    key_pattern: str,
) -> Callable[[Callable[..., Awaitable[Any]]], Callable[..., Awaitable[Any]]]:
    """Декоратор: после успешного выполнения функции инвалидирует кеш по pattern'у.

    Args:
        key_pattern: glob-pattern (например ``"bki:*"``).

    Returns:
        Декоратор для async-функции.
    """

    def decorator(func: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
        if not asyncio.iscoroutinefunction(func):
            raise TypeError("@invalidate поддерживает только async-функции")

        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            result = await func(*args, **kwargs)
            # Lazy-import redis_client — core не должен иметь статической
            # зависимости от infrastructure.
            try:
                from src.backend.core.di.providers.infrastructure_facade import (
                    get_redis_client_factory as _get_redis_client_fn,
                )
                get_redis_client = _get_redis_client_fn()

                redis_client = get_redis_client()
                await redis_client.cache_delete_pattern(key_pattern)
            except Exception as exc:
                # Best-effort инвалидация; ошибки кеша не должны рушить
                # mutating-операцию.
                _logger.debug(
                    "cache_invalidate: redis unavailable (%s), skipping invalidation",
                    exc,
                )
            return result

        return wrapper

    return decorator


def multi_cached(
    *, ttls: Mapping[str, int]
) -> Callable[[Callable[..., Awaitable[Any]]], Callable[..., Awaitable[Any]]]:
    """Декоратор: несколько slots кеша с разными TTL.

    Каждый slot — отдельный key-prefix. Результат функции должен быть dict;
    ключи ``ttls`` мэппятся на ключи результата (например ``{"summary": 60,
    "raw": 600}`` — два разных TTL для двух разделов ответа).

    Args:
        ttls: Маппинг ``<slot> → <ttl_seconds>``.

    Returns:
        Декоратор. Для простоты текущая реализация использует **минимальный**
        TTL из ``ttls`` (стандартный multi-layer fallback). Полная per-slot
        семантика — follow-up в S2 K2.
    """
    if not ttls:
        raise ValueError("@multi_cached требует непустого ttls")
    min_ttl = min(ttls.values())

    def decorator(func: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
        slots = ",".join(sorted(ttls))

        def _key_builder(*args: Any, **kwargs: Any) -> str:
            return build_cache_key(func, args, kwargs, prefix=f"multi:{slots}")

        return cached(ttl=min_ttl, key=_key_builder, backend="multi")(func)

    return decorator
