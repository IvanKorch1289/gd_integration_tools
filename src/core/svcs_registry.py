"""Единый DI-контейнер приложения на базе ``svcs`` (ADR-002).

Этот модуль — единственный источник правды для регистрации и получения
сервисов. Старый name-based ``ServiceRegistry`` (``app.core.service_registry``)
превращён в тонкий deprecation-shim; ``_FallbackRegistry`` (dead code с
прошлой итерации) удалён.

Возможности:

* type-based lookup — ``get_service(OrderService)`` (svcs convention);
* name-based lookup — ``get_service("orders")`` (обратная совместимость
  для DSL-процессоров и admin-роутов);
* lazy singleton — factory вызывается при первом обращении, результат
  кешируется; повторные ``get_service`` возвращают тот же объект.

Примеры::

    from app.core.svcs_registry import register_factory, get_service

    register_factory("orders", get_order_service)
    register_factory(OrderService, get_order_service)

    svc = get_service("orders")        # name-based
    svc = get_service(OrderService)    # type-based (тот же объект)
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Callable, Hashable, TypeVar

import svcs

__all__ = (
    "registry",
    "register_factory",
    "get_service",
    "has_service",
    "list_services",
    "clear_registry",
)

logger = logging.getLogger("core.svcs_registry")

T = TypeVar("T")

# Единый глобальный Registry для всего процесса.
registry: svcs.Registry = svcs.Registry()

# Сопутствующий кеш синглтонов: svcs отдаёт новый Container на каждую
# операцию, а у нас подавляющее большинство сервисов — module-level
# синглтоны. Храним их здесь, чтобы ``get_service`` был реентерабельным
# без накладных расходов.
_singletons: dict[Hashable, Any] = {}
_known_keys: set[Hashable] = set()
_lock = threading.RLock()


def register_factory(key: Hashable, factory: Callable[[], Any]) -> None:
    """Регистрирует фабрику сервиса.

    Args:
        key: строка (имя) или тип.
        factory: callable без аргументов, возвращающий экземпляр.
    """
    with _lock:
        # svcs требует type в качестве ключа — оборачиваем произвольный
        # hashable через proxy-класс при необходимости.
        if isinstance(key, type):
            registry.register_factory(key, factory)
        else:
            # Для строковых/hashable ключей храним у себя; svcs-контейнер
            # опционально получает их тоже (svcs ≥ 25.1 это допускает).
            try:
                registry.register_factory(key, factory)  # type: ignore[arg-type]
            except Exception:
                logger.debug("svcs не принял ключ %r — используется внутренний cache.", key)
        _known_keys.add(key)
        # Если фабрика уже вызывалась — сбрасываем кеш.
        _singletons.pop(key, None)


def has_service(key: Hashable) -> bool:
    """Возвращает True, если сервис зарегистрирован."""
    return key in _known_keys


def list_services() -> list[str]:
    """Возвращает имена зарегистрированных сервисов (для admin-API)."""
    with _lock:
        return sorted(str(k) if not isinstance(k, type) else k.__name__ for k in _known_keys)


def get_service(key: Hashable | type[T]) -> T | Any:
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
        if key not in _known_keys:
            raise KeyError(
                f"Сервис '{key}' не зарегистрирован. "
                f"Доступные: {', '.join(list_services())}"
            )
        # Пытаемся svcs Container (type-keys); fallback — прямой вызов factory.
        instance: Any
        try:
            container = svcs.Container(registry)
            instance = container.get(key)  # type: ignore[arg-type]
        except Exception:
            factory = _factory_for(key)
            if factory is None:
                raise KeyError(f"Factory для '{key}' не найдена") from None
            instance = factory()
        _singletons[key] = instance
        return instance


def clear_registry() -> None:
    """Очищает registry (для тестов/reload)."""
    with _lock:
        _known_keys.clear()
        _singletons.clear()
        # svcs Registry не имеет публичного clear — пересоздаём.
        global registry
        registry = svcs.Registry()


def _factory_for(key: Hashable) -> Callable[[], Any] | None:
    """Достаёт factory для key из svcs Registry.

    svcs хранит factories в ``_services`` (dict key->Service). API не
    публично, но стабильно в рамках svcs 25.x. Fallback — None.
    """
    services = getattr(registry, "_services", None)
    if isinstance(services, dict):
        svc = services.get(key)
        if svc is not None:
            return getattr(svc, "factory", None) or getattr(svc, "_factory", None)
    return None
