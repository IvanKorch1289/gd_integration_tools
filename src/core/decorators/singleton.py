"""Thread-safe Singleton декоратор.

Гарантирует создание единственного экземпляра класса
даже при многопоточном доступе (double-checked locking).
"""

import threading
from functools import wraps
from typing import Any

__all__ = ("singleton",)


def singleton(cls: type) -> Any:
    """Декоратор для создания Singleton-класса.

    Использует ``threading.Lock`` + double-checked locking
    для потокобезопасности.

    Args:
        cls: Класс, который нужно сделать Singleton.

    Returns:
        Обёртка, возвращающая единственный экземпляр.
    """
    instance: list[Any] = [None]
    lock = threading.Lock()

    @wraps(cls)
    def get_instance(*args: Any, **kwargs: Any) -> Any:
        if instance[0] is None:
            with lock:
                if instance[0] is None:
                    instance[0] = cls(*args, **kwargs)
        return instance[0]

    return get_instance
