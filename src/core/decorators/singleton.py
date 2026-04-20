"""Thread-safe Singleton декоратор с возможностью сброса в тестах.

Гарантирует создание единственного экземпляра класса даже при многопоточном
доступе (double-checked locking). Дополнительно предоставляет:

* :func:`reset_singletons` — сброс всех инстансов (для тестов / hot-reload).
* ``get_instance.reset()`` — сброс конкретного singleton'а.
* ``get_instance.instance`` — доступ к текущему инстансу без конструирования.

Важно: декоратор принимает ``*args, **kwargs`` для обратной совместимости,
но учитывайте — аргументы передаются **только при первом вызове**. Если
нужен singleton с параметрами — вынесите инициализацию в явный ``get_xxx_service()``.
"""

from __future__ import annotations

import threading
import weakref
from functools import wraps
from typing import Any, Callable

__all__ = ("singleton", "reset_singletons")

# Слабые ссылки на все обёртки get_instance — для reset_singletons().
# WeakSet: не мешает GC классов, автоматически очищается при их удалении.
_registry: weakref.WeakSet[Callable[..., Any]] = weakref.WeakSet()


def singleton(cls: type) -> Any:
    """Превращает класс в singleton с lazy-инициализацией.

    Args:
        cls: Декорируемый класс.

    Returns:
        Функция-обёртка. При первом вызове создаёт инстанс, далее возвращает
        кешированный. Аргументы конструктора принимаются, но работают только
        при первом вызове.

    Example::

        @singleton
        class MyService:
            def __init__(self) -> None:
                self.connections = 0

        s1 = MyService()
        s2 = MyService()
        assert s1 is s2  # True
    """
    instance: Any = None
    lock = threading.Lock()

    @wraps(cls, updated=())  # updated=() — класс не имеет __dict__-mergeable атрибутов
    def get_instance(*args: Any, **kwargs: Any) -> Any:
        """Возвращает (или создаёт) единственный инстанс."""
        nonlocal instance
        if instance is None:
            with lock:
                if instance is None:
                    instance = cls(*args, **kwargs)
        return instance

    def _reset() -> None:
        """Сбрасывает инстанс (следующий вызов пересоздаст)."""
        nonlocal instance
        with lock:
            instance = None

    def _get_instance_or_none() -> Any:
        """Возвращает инстанс без конструирования (None если не создан)."""
        return instance

    # Навешиваем вспомогательные функции на get_instance — удобно для тестов.
    get_instance.reset = _reset  # type: ignore[attr-defined]
    get_instance.instance = property(lambda _: _get_instance_or_none())  # type: ignore[attr-defined]

    _registry.add(get_instance)
    return get_instance


def reset_singletons() -> int:
    """Сбрасывает все singleton-инстансы (для unit-тестов или hot-reload).

    Returns:
        Количество сброшенных singleton'ов.
    """
    count = 0
    for wrapper in list(_registry):
        reset_fn = getattr(wrapper, "reset", None)
        if callable(reset_fn):
            reset_fn()
            count += 1
    return count
