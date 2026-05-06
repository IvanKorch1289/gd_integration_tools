"""Утилиты ядра общего назначения.

Содержит:

- ``async_helpers`` — async-итераторы (``AsyncChunkIterator``);
- ``async_utils`` — asyncer-обёртки (``run_sync_in_thread``,
  ``gather_with_timeout``, ``async_with_timeout``);
- ``circuit_breaker`` — простейший circuit-breaker (исторический модуль).
"""

from src.backend.core.utils.async_helpers import AsyncChunkIterator
from src.backend.core.utils.async_utils import (
    async_with_timeout,
    gather_with_timeout,
    run_sync_in_thread,
)

__all__ = (
    "AsyncChunkIterator",
    "async_with_timeout",
    "gather_with_timeout",
    "run_sync_in_thread",
)
