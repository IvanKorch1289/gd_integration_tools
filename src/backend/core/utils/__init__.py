"""Утилиты ядра общего назначения.

Содержит:

- ``async_helpers`` — async-итераторы (``AsyncChunkIterator``);
- ``async_utils`` — asyncer-обёртки (``run_sync_in_thread``,
  ``gather_with_timeout``, ``async_with_timeout``);
- ``circuit_breaker`` — простейший circuit-breaker (исторический модуль);
- ``task_registry`` — централизованный реестр фоновых ``asyncio.Task``
  (V15 R-V15-11);
- ``watchdog`` — deadline-эскалация для long-running async-задач.
"""

from src.backend.core.utils.async_helpers import AsyncChunkIterator
from src.backend.core.utils.async_utils import (
    async_with_timeout,
    gather_with_timeout,
    run_sync_in_thread,
)
from src.backend.core.utils.task_registry import (
    TaskRegistry,
    get_task_registry,
    reset_task_registry,
)
from src.backend.core.utils.watchdog import Watchdog

__all__ = (
    "AsyncChunkIterator",
    "TaskRegistry",
    "Watchdog",
    "async_with_timeout",
    "gather_with_timeout",
    "get_task_registry",
    "reset_task_registry",
    "run_sync_in_thread",
)
