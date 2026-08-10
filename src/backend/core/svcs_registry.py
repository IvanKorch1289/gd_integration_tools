"""Единый DI-контейнер приложения — plain dict registry (ADR-002, D1_SVCS_REGISTRY).

Этот модуль — единственный источник правды для регистрации и получения
сервисов. Ранее строился поверх библиотеки ``svcs``, но ``svcs`` требовала
type-based ключей и хранила factories в приватном ``_services``; в 90% случаев
срабатывал внутренний кеш, а ``_factory_for()`` лез в private API.

Теперь — простой dict (как ``providers_registry``): меньше зависимостей,
нулевая магия, ponytail.

Возможности:

* type-based lookup — ``get_service(OrderService)``;
* name-based lookup — ``get_service("orders")`` (для DSL-процессоров
  и admin-роутов);
* lazy singleton — factory вызывается при первом обращении, результат
  кешируется; повторные ``get_service`` возвращают тот же объект.

Примеры::

    from src.backend.core.svcs_registry import register_factory, get_service

    register_factory("orders", get_order_service)
    register_factory(OrderService, get_order_service)

    svc = get_service("orders")        # name-based
    svc = get_service(OrderService)    # type-based (тот же объект)
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Hashable
from typing import Any, TypeVar, cast

__all__ = (
    "clear_registry",
    "get_service",
    "has_service",
    "list_services",
    "register_factory",
)


T = TypeVar("T")

# Фабрики: key -> callable без аргументов. Lazy instantiation.
_factories: dict[Hashable, Callable[[], Any]] = {}
# Кеш синглтонов: factory вызывается один раз, результат кешируется.
_singletons: dict[Hashable, Any] = {}
_lock = threading.Lock()


def register_factory(key: Hashable, factory: Callable[[], Any]) -> None:
    """Регистрирует фабрику сервиса.

    Args:
        key: строка (имя) или тип.
        factory: callable без аргументов, возвращающий экземпляр.

    Повторная регистрация сбрасывает закешированный синглтон (чтобы
    ``register_factory`` можно было использовать для override в тестах).

    """
    with _lock:
        _factories[key] = factory
        # Если фабрика уже вызывалась — сбрасываем кеш.
        _singletons.pop(key, None)


def has_service(key: Hashable) -> bool:
    """Возвращает True, если сервис зарегистрирован."""
    with _lock:
        return key in _factories


def list_services() -> list[str]:
    """Возвращает имена зарегистрированных сервисов (для admin-API)."""
    with _lock:
        return sorted(
            str(k) if not isinstance(k, type) else k.__name__
            for k in _factories
        )


def get_service[T](key: Hashable | type[T]) -> T | Any:
    """Получает экземпляр сервиса (singleton).

    Args:
        key: строка-имя или тип.

    Returns:
        Инстанс сервиса.

    Raises:
        KeyError: если ``key`` не зарегистрирован.

    """
    with _lock:
        if key in _singletons:
            return _singletons[key]
        factory = _factories.get(key)
        if factory is None:
            available = ", ".join(
                str(k) if not isinstance(k, type) else k.__name__
                for k in sorted(_factories, key=lambda x: str(x))
            )
            raise KeyError(
                f"Сервис '{key}' не зарегистрирован. Доступные: {available}",
            )
        instance = factory()
        _singletons[cast(Hashable, key)] = instance
        return instance


def clear_registry() -> None:
    """Очищает registry (для тестов/reload)."""
    with _lock:
        _factories.clear()
        _singletons.clear()
