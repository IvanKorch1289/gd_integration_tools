"""Утилиты для построения детерминированных ключей кэша.

Wave 3: единая функция ``build_cache_key`` для всех слоёв кэширования,
чтобы избежать дублирования логики сериализации между
`CachingDecorator` и `@multi_cached`.
"""

from __future__ import annotations

import hashlib
from collections.abc import Awaitable, Callable
from typing import Any

import orjson


def build_cache_key(
    func: Callable[..., Awaitable[Any]],
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    *,
    prefix: str = "cache",
    exclude_self: bool = False,
) -> str:
    """Построить детерминированный SHA256-ключ для кэша.

    Args:
        func: Декорируемая функция.
        args: Позиционные аргументы.
        kwargs: Именованные аргументы.
        prefix: Префикс ключа.
        exclude_self: Исключить первый аргумент (self/cls) из ключа.

    Returns:
        Строка ключа вида ``prefix:<sha256>``.

    """
    key_data = {
        "module": func.__module__,
        "name": func.__name__,
        "args": args[1:] if exclude_self and args else args,
        "kwargs": dict(sorted(kwargs.items())),
    }
    payload = orjson.dumps(
        key_data, option=orjson.OPT_SORT_KEYS | orjson.OPT_NON_STR_KEYS, default=str
    ).decode("utf-8")
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"{prefix}:{digest}"
