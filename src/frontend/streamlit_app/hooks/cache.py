"""Кэширующие декораторы для Streamlit."""

from __future__ import annotations

from typing import Any, Callable, TypeVar, overload

import streamlit as st

F = TypeVar("F", bound=Callable[..., Any])


@overload
def cached_data(func: F) -> F: ...


@overload
def cached_data(func: None = None, *, ttl: int = 300) -> Callable[[F], F]: ...


def cached_data(func: F | None = None, *, ttl: int = 300) -> F | Callable[[F], F]:
    """Декоратор для кэширования данных с TTL.

    Args:
        func: Функция для декорирования.
        ttl: Время жизни кэша в секундах.

    Returns:
        Декорированная функция или декоратор.
    """

    def decorator(fn: F) -> F:
        return st.cache_data(ttl=ttl, show_spinner=False)(fn)  # type: ignore[return-value]

    if func is None:
        return decorator
    return decorator(func)


def cached_resource(ttl: int = 3600) -> Callable[[F], F]:
    """Декоратор для кэширования ресурсов (клиенты, подключения).

    Args:
        ttl: Время жизни кэша в секундах.

    Returns:
        Декоратор.
    """

    def decorator(fn: F) -> F:
        return st.cache_resource(ttl=ttl, show_spinner=False)(fn)  # type: ignore[return-value]

    return decorator
