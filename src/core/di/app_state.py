"""App-state singleton accessor: pure-Python DI-примитив.

Декоратор ``app_state_singleton`` переводит функцию ``get_xxx()``
в singleton-accessor через ``app.state``. Сначала ищется значение
в ``app.state``, затем (для non-request контекстов) lazy-init
через factory.

Не импортирует ничего из infrastructure/services/entrypoints —
размещён в core/, чтобы любой слой мог пользоваться декоратором
без нарушения layer policy.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable, TypeVar

if TYPE_CHECKING:
    from fastapi import FastAPI

T = TypeVar("T")

__all__ = ("app_state_singleton", "get_app_ref", "set_app_ref")

# Ссылка на FastAPI-приложение, сохраняется при первой инициализации
# (см. infrastructure.application.di.register_app_state) и используется
# в non-request контекстах (CLI, scripts, DSL engine).
_app_ref: FastAPI | None = None


def set_app_ref(app: FastAPI) -> None:
    """Регистрирует ссылку на FastAPI-app для non-request контекстов.

    Вызывается ровно один раз из ``register_app_state`` при старте.
    """
    global _app_ref
    _app_ref = app


def get_app_ref() -> FastAPI | None:
    """Возвращает зарегистрированный FastAPI-app либо ``None``."""
    return _app_ref


def _get_from_app_state(attr: str) -> Any | None:
    """Безопасно достаёт ``app.state.<attr>`` — для non-request контекстов.

    Args:
        attr: Имя атрибута в ``app.state``.

    Returns:
        Значение атрибута либо ``None``, если app ещё не инициализирован
        или атрибут отсутствует.
    """
    if _app_ref is not None:
        return getattr(_app_ref.state, attr, None)
    return None


def app_state_singleton(
    attr: str, factory: Callable[[], T] | None = None
) -> Callable[[Callable[[], T]], Callable[[], T]]:
    """Декоратор-фабрика singleton-доступа к объектам из ``app.state``.

    Убирает дублированный паттерн ``def get_xxx(): return app.state.xxx``.
    Сначала ищет объект в ``app.state``, затем lazy-init через factory
    (для контекстов без FastAPI).

    Args:
        attr: Имя атрибута в ``app.state``.
        factory: Опциональная фабрика для lazy-init в non-request контекстах.

    Returns:
        Декоратор, превращающий функцию-заглушку в accessor singleton'а.
    """
    _cache: dict[str, Any] = {}

    def decorator(fn: Callable[[], T]) -> Callable[[], T]:
        def wrapper() -> T:
            instance = _get_from_app_state(attr)
            if instance is not None:
                return instance
            if attr not in _cache:
                if factory is not None:
                    _cache[attr] = factory()
                else:
                    raise RuntimeError(
                        f"{attr} not in app.state and no factory provided. "
                        "Ensure register_app_state() was called."
                    )
            return _cache[attr]

        wrapper.__name__ = fn.__name__
        wrapper.__doc__ = fn.__doc__
        wrapper.__qualname__ = fn.__qualname__
        return wrapper

    return decorator
