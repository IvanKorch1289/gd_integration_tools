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

import logging
from typing import TYPE_CHECKING, Any, Callable, TypeVar

if TYPE_CHECKING:
    from fastapi import FastAPI

T = TypeVar("T")

__all__ = (
    "app_state_singleton",
    "get_app_ref",
    "require_app_ref",
    "reset_app_state",
    "set_app_ref",
)

logger = logging.getLogger(__name__)

# Ссылка на FastAPI-приложение, сохраняется при первой инициализации
# (см. plugins.composition.di.register_app_state) и используется
# в non-request контекстах (CLI, scripts, DSL engine).
_app_ref: FastAPI | None = None

# Реестр всех closure-cache'ей декораторов app_state_singleton.
# Заполняется при создании декоратора, очищается через reset_app_state()
# (для изоляции тестовых сессий с повторным create_app()).
_DECORATOR_CACHES: list[dict[str, Any]] = []


def set_app_ref(app: FastAPI, *, allow_replace: bool = False) -> None:
    """Регистрирует ссылку на FastAPI-app для non-request контекстов.

    Вызывается ровно один раз из ``register_app_state`` при старте.

    Args:
        app: Экземпляр FastAPI-приложения.
        allow_replace: При ``True`` — заменяет существующую ссылку без warning
            (для тестов с повторным ``create_app()``). При ``False`` (default)
            — логирует warning, если предыдущая ссылка ещё не сброшена через
            ``reset_app_state()``.
    """
    global _app_ref
    if _app_ref is not None and not allow_replace:
        logger.warning(
            "set_app_ref вызван повторно без reset_app_state — "
            "предыдущая ссылка перезаписывается. Это может привести "
            "к flaky-тестам, если декораторные кэши не очищены."
        )
    _app_ref = app


def get_app_ref() -> FastAPI | None:
    """Возвращает зарегистрированный FastAPI-app либо ``None``."""
    return _app_ref


def require_app_ref() -> FastAPI:
    """Возвращает зарегистрированный FastAPI-app или поднимает RuntimeError.

    Использовать в "горячих" провайдерах, где доступ к app.state
    обязателен после ``register_app_state()``.

    Raises:
        RuntimeError: Если ``set_app_ref()`` ещё не вызывался.
    """
    if _app_ref is None:
        raise RuntimeError(
            "FastAPI app не зарегистрирован: вызовите set_app_ref() "
            "перед обращением к зависимостям через app.state. Обычно это "
            "делается автоматически в register_app_state() при старте."
        )
    return _app_ref


def reset_app_state() -> None:
    """Сбрасывает _app_ref и все кэши декораторов app_state_singleton.

    Предназначено для pytest teardown между сессиями с повторным
    ``create_app()``: без этого сброса повторный старт получит
    закэшированные factory-инстансы из предыдущего цикла.
    """
    global _app_ref
    _app_ref = None
    for cache in _DECORATOR_CACHES:
        cache.clear()


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

    Внутренний кэш регистрируется в ``_DECORATOR_CACHES`` и очищается
    функцией ``reset_app_state()`` — это критично для изоляции тестов
    с повторным ``create_app()``.

    Args:
        attr: Имя атрибута в ``app.state``.
        factory: Опциональная фабрика для lazy-init в non-request контекстах.

    Returns:
        Декоратор, превращающий функцию-заглушку в accessor singleton'а.
    """
    _cache: dict[str, Any] = {}
    _DECORATOR_CACHES.append(_cache)

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
                        "Ensure register_app_state() was called or provide "
                        "factory=... к app_state_singleton."
                    )
            return _cache[attr]

        wrapper.__name__ = fn.__name__
        wrapper.__doc__ = fn.__doc__
        wrapper.__qualname__ = fn.__qualname__
        return wrapper

    return decorator
