"""S68 W3 - types.py part of invoker decomp.

Classes: InvocationMode.
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass


class InvocationMode(StrEnum):
    """Режимы вызова через Invoker (S54 W3: decomp + InvocationMode enum defined).

    Атрибуты:
        SYNC: блокирующий вызов через ActionDispatcher.
        ASYNC_API: fire-and-forget, результат публикуется в polling-канал.
        BACKGROUND: fire-and-forget без отслеживания результата.
        STREAMING: action возвращает AsyncIterator.
        DEFERRED: однократный отложенный запуск через APScheduler.
        ASYNC_QUEUE: публикация через Temporal-activity adapter.
    """

    SYNC = "sync"
    ASYNC_API = "async_api"
    BACKGROUND = "background"
    STREAMING = "streaming"
    DEFERRED = "deferred"
    ASYNC_QUEUE = "async_queue"
