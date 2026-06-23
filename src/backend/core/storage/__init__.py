"""Core storage capability-checked facades (S123 W1, S36-W23).

Sub-modules:
- redis: re-export of infrastructure.clients.storage.redis.get_redis_client

S36-W23: добавлены single entry points для объектного хранилища
через DI providers — extensions могут получать ``StorageFacade``
без прямого импорта из ``services.storage.facade`` (boundary rule).
"""

from __future__ import annotations

# S36-W23: re-export DI providers для single entry point
from src.backend.core.di.providers import (  # noqa: F401
    get_object_storage_provider,
    get_storage_facade_provider,
    set_object_storage_provider,
    set_storage_facade_provider,
)

__all__ = (
    "get_object_storage_provider",
    "get_storage_facade_provider",
    "set_object_storage_provider",
    "set_storage_facade_provider",
)
