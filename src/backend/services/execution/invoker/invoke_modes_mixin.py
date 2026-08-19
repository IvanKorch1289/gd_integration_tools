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

import asyncio

from src.backend.core.interfaces.invocation_reply import ReplyChannelKind
from src.backend.core.interfaces.invoker import (
    InvocationRequest,
    InvocationResponse,
    InvocationStatus,
)
from src.backend.core.logging import get_logger
from src.backend.core.types.invocation_command import ActionCommandSchema
from src.backend.core.utils.task_registry import get_task_registry

logger = get_logger("services.execution.invoker")


class InvokeModesMixin:
    """synchronous + async_api + background invocation modes для Invoker. S54 W3 extraction."""

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

    _invoke_streaming: Any
    _invoke_deferred: Any
    _select_deferred_jobstore: Any
    _resolve_deferred_run_at: Any
    _invoke_async_queue: Any
    _invoke_via_temporal_adapter: Any
    _run_temporal_activity: Any
    __slots__ = ()

    async def _invoke_sync(self, request: InvocationRequest) -> InvocationResponse:
        try:
            command = ActionCommandSchema(
                action=request.action, payload=request.payload
            )
            context = self._build_context(request)
            if request.timeout is not None:
                result: Any = await asyncio.wait_for(
                    self._dispatch(command, context), timeout=request.timeout
                )
            else:
                result = await self._dispatch(command, context)
            return InvocationResponse(
                invocation_id=request.invocation_id,
                status=InvocationStatus.OK,
                result=result,
                mode=request.mode,
                metadata=dict(request.metadata),
            )
        except TimeoutError:
            logger.warning(
                "Invoker SYNC timeout: action=%s id=%s after %ss",
                request.action,
                request.invocation_id,
                request.timeout,
            )
            return InvocationResponse(
                invocation_id=request.invocation_id,
                status=InvocationStatus.ERROR,
                error=f"SYNC timeout after {request.timeout}s",
                mode=request.mode,
                metadata=dict(request.metadata),
            )
        except KeyError as exc:
            return InvocationResponse(
                invocation_id=request.invocation_id,
                status=InvocationStatus.ERROR,
                error=f"Action not registered: {exc}",
                mode=request.mode,
                metadata=dict(request.metadata),
            )
        except Exception as exc:
            logger.exception(
                "Invoker.invoke failed: action=%s id=%s",
                request.action,
                request.invocation_id,
            )
            return InvocationResponse(
                invocation_id=request.invocation_id,
                status=InvocationStatus.ERROR,
                error=str(exc)[:500],
                mode=request.mode,
                metadata=dict(request.metadata),
            )

    def _invoke_async_api(self, request: InvocationRequest) -> InvocationResponse:
        """Запускает action в фоновом task'е и публикует результат в polling-канал."""
        channel = self._resolve_channel(
            request.reply_channel or ReplyChannelKind.API.value
        )
        task = get_task_registry().create_task(
            self._run_and_publish(request, channel),
            name=f"invoker:async-api:{request.invocation_id}",
        )
        self._track(task)
        return InvocationResponse(
            invocation_id=request.invocation_id,
            status=InvocationStatus.ACCEPTED,
            mode=request.mode,
        )

    def _invoke_background(self, request: InvocationRequest) -> InvocationResponse:
        """Fire-and-forget без сохранения результата."""
        task = get_task_registry().create_task(
            self._run_silent(request),
            name=f"invoker:background:{request.invocation_id}",
        )
        self._track(task)
        return InvocationResponse(
            invocation_id=request.invocation_id,
            status=InvocationStatus.ACCEPTED,
            mode=request.mode,
        )
