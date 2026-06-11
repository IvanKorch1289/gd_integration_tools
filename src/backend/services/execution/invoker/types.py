from __future__ import annotations
"""S68 W3 - types.py part of invoker decomp.

Classes: InvocationMode.
"""

from enum import StrEnum

from typing import TYPE_CHECKING, Any

from datetime import UTC, datetime, timedelta

from src.backend.core.logging import get_logger

from src.backend.core.interfaces.invocation_reply import ReplyChannelKind
from src.backend.core.interfaces.invoker import InvocationRequest, InvocationResponse
from src.backend.dsl.engine.context import ExecutionContext

if TYPE_CHECKING:
    pass

from src.backend.services.execution.invoker.invoke_modes_mixin import InvokeModesMixin  # S54 W3: MRO
from src.backend.services.execution.invoker.deferred_mixin import DeferredMixin  # S54 W3: MRO
from src.backend.services.execution.invoker.temporal_mixin import TemporalMixin  # S54 W3: MRO
from src.backend.services.execution.invoker.run_mixin import RunMixin  # S54 W3: MRO

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

