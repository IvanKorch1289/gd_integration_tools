from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass  # cross-mixin / state attrs declared below

"""Реализация Invoker (W22.1 + W22.2/W22.3 + Этап B расширения).

Поддерживает шесть режимов:

* :attr:`InvocationMode.SYNC` — блокирующий вызов через ActionDispatcher.
* :attr:`InvocationMode.ASYNC_API` — fire-and-forget, результат
  публикуется в polling-канал (:class:`MemoryReplyChannel`); клиент
  опрашивает ``GET /api/v1/invocations/{id}``.
* :attr:`InvocationMode.BACKGROUND` — fire-and-forget без отслеживания
  результата.
* :attr:`InvocationMode.STREAMING` — action возвращает ``AsyncIterator``;
  каждый yield пушится в :class:`WsReplyChannel` для зарегистрированного
  invocation_id. Завершение stream'а — закрытие WS со стороны клиента.
* :attr:`InvocationMode.DEFERRED` — однократный отложенный запуск через
  APScheduler (``request.metadata['run_at']`` ISO-datetime или
  ``request.metadata['delay_seconds']``). Не durable — после рестарта
  сервиса задача не восстанавливается (memory jobstore).
* :attr:`InvocationMode.ASYNC_QUEUE` — публикация через Temporal-activity
  adapter (Sprint 8 K2 W1: TaskIQ полностью удалён).
"""

from typing import Any

from src.backend.core.interfaces.invocation_reply import (
    InvocationReplyChannel,
    ReplyChannelKind,
)
from src.backend.core.interfaces.invoker import (
    InvocationRequest,
    InvocationResponse,
    InvocationStatus,
)
from src.backend.core.logging import get_logger
from src.backend.core.utils.task_registry import get_task_registry

logger = get_logger("services.execution.invoker")

class TemporalMixin:
    """async queue + Temporal adapter + Temporal activity execution для Invoker. S54 W3 extraction."""

    # State attrs + cross-method hints (S54 W3: class-level annotations for mypy MRO)
    _resolve_reply_registry: Any
    _dispatch: Any
    _build_context: Any
    _tasks: Any
    _resolve_channel: Any
    _track: Any
    _run_and_publish: Any
    _run_silent: Any
    _run_and_stream: Any
    _invoke_sync: Any
    _invoke_async_api: Any
    _invoke_background: Any
    _invoke_streaming: Any
    _invoke_deferred: Any
    _select_deferred_jobstore: Any
    _resolve_deferred_run_at: Any

    __slots__ = ()

    async def _invoke_async_queue(
        self, request: InvocationRequest
    ) -> InvocationResponse:
        """Публикует invocation в очередь через Temporal-activity-adapter.

        K2 W1 (Sprint 8): TaskIQ полностью удалён. Все ASYNC_QUEUE-callsite
        идут через :func:`wrap_as_temporal_activity` — direct-async-execution
        обёрнутого action. Full-blown Temporal workflow с durable replay
        подключается в Sprint 6 (R-V15-7).
        """
        return await self._invoke_via_temporal_adapter(request)

    async def _invoke_via_temporal_adapter(
        self, request: InvocationRequest
    ) -> InvocationResponse:
        """K2 W1: Temporal-activity-adapter путь для ASYNC_QUEUE.

        Wrap'ит SYNC-invoke в TemporalActivityWrapper и выполняет.
        Reply-channel публикация остаётся синхронной — full-blown
        Temporal workflow с durable replay добавится в Sprint 6.
        """
        from src.backend.core.orchestration.temporal_activity_adapter import (
            wrap_as_temporal_activity,
        )

        channel = self._resolve_channel(
            request.reply_channel or ReplyChannelKind.API.value
        )

        async def _execute() -> InvocationResponse:
            return await self._invoke_sync(request)

        activity = wrap_as_temporal_activity(
            _execute, name=f"invoker.async_queue:{request.action}"
        )
        task = get_task_registry().create_task(
            self._run_temporal_activity(activity, request, channel),
            name=f"invoker:temporal-activity:{request.invocation_id}",
        )
        self._track(task)
        return InvocationResponse(
            invocation_id=request.invocation_id,
            status=InvocationStatus.ACCEPTED,
            mode=request.mode,
            metadata=dict(request.metadata),
        )

    async def _run_temporal_activity(
        self,
        activity: Any,
        request: InvocationRequest,
        channel: InvocationReplyChannel | None,
    ) -> None:
        """Выполняет Temporal-activity wrapper и публикует результат."""
        try:
            response = await activity()
        except Exception as exc:
            logger.exception(
                "Temporal-activity invoke failed (invocation_id=%s)",
                request.invocation_id,
            )
            response = InvocationResponse(
                invocation_id=request.invocation_id,
                status=InvocationStatus.ERROR,
                error=f"Temporal activity failed: {exc}",
                mode=request.mode,
                metadata=dict(request.metadata),
            )
        if channel is not None:
            try:
                await channel.send(response)
            except Exception as _:
                logger.exception(
                    "Temporal-activity: ReplyChannel.send failed (id=%s)",
                    request.invocation_id,
                )

