"""Кэширующие декораторы для Streamlit."""

from __future__ import annotations

import functools
from collections.abc import Callable
from typing import Any, ParamSpec, Protocol, TypeVar, cast, overload

import streamlit as st

F = TypeVar("F", bound=Callable[..., Any])
P = ParamSpec("P")
R = TypeVar("R")
R_co = TypeVar("R_co", covariant=True)


class ScopedCachedFunc(Protocol[P, R_co]):
    """Кэшированная функция с методом ``clear`` (как у ``st.cache_data``)."""

    def __call__(self, *args: P.args, **kwargs: P.kwargs) -> R_co: ...

    clear: Callable[[], None]


@overload
def cached_data(func: F) -> F:
    """Метод cached_data (см. signature)."""


@overload
def cached_data(func: None = None, *, ttl: int = 300) -> Callable[[F], F]:
    """Метод cached_data (см. signature)."""


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


def user_scoped_cache_data(
    *, ttl: int = 60, show_spinner: bool = False
) -> Callable[[Callable[P, R]], ScopedCachedFunc[P, R]]:
    """``st.cache_data`` с user-scope в ключе — изоляция кэша между сессиями.

    ``st.cache_data`` — процесс-глобальный кэш: записи видны всем
    пользователям портала. Если scope (JWT-диigest) не входит в ключ,
    данные одного пользователя/тенанта отдаются другому.

    Аргумент scope намеренно **без** подчёркивания: Streamlit исключает
    из ключа параметры с префиксом ``_`` (см. ``cache_utils._make_key``).

    Args:
        ttl: Время жизни кэша в секундах.
        show_spinner: Показывать ли спиннер при пересчёте.

    Returns:
        Декоратор, добавляющий scope в ключ кэша.

    """

    def decorator(fn: Callable[P, R]) -> ScopedCachedFunc[P, R]:
        @st.cache_data(ttl=ttl, show_spinner=show_spinner)
        def _scoped(scope: str, *args: P.args, **kwargs: P.kwargs) -> R:
            return fn(*args, **kwargs)

        @functools.wraps(fn)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            # Lazy-import: auth_state тянет api_clients — локальный импорт
            # исключает цикл на этапе импорта модулей.
            from src.frontend.streamlit_app.shared.auth_state import (
                get_auth_cache_scope,
            )

            return _scoped(get_auth_cache_scope(), *args, **kwargs)

        # ``clear`` есть только у настоящего CachedFunc; в тестовых моках
        # ``st.cache_data`` возвращает голую функцию — не падаем на этом.
        clear = getattr(_scoped, "clear", None)
        if clear is not None:
            wrapper.clear = clear  # type: ignore[attr-defined]
        return cast("ScopedCachedFunc[P, R]", wrapper)

    return decorator
