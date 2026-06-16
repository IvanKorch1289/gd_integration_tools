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

from src.backend.core.interfaces.invocation_reply import InvocationReplyChannel
from src.backend.core.interfaces.invoker import (
    InvocationRequest,
    InvocationResponse,
    InvocationStatus,
)
from src.backend.core.logging import get_logger
from src.backend.core.types.invocation_command import ActionCommandSchema
from src.backend.services.execution.invoker.helpers import _is_async_iterator  # S149 W2: missing import (S68 W3 decomp lost it)

logger = get_logger("services.execution.invoker")


class RunMixin:
    """run helpers (channel resolution, tracking, publishing, silent, streaming) для Invoker. S54 W3 extraction."""

    # State attrs + cross-method hints (S54 W3: class-level annotations for mypy MRO)
    _resolve_reply_registry: Any
    _dispatch: Any
    _build_context: Any
    _tasks: Any

    _invoke_sync: Any
    _invoke_async_api: Any
    _invoke_background: Any
    _invoke_streaming: Any
    _invoke_deferred: Any
    _select_deferred_jobstore: Any
    _resolve_deferred_run_at: Any
    _invoke_async_queue: Any
    _invoke_via_temporal_adapter: Any
    _run_temporal_activity: Any
    _is_async_iterator: Any  # top-level helper in __init__.py

    __slots__ = ()

    def _resolve_channel(self, name: str) -> InvocationReplyChannel | None:
        """Получает backend по имени (kind) или возвращает None."""
        registry = self._resolve_reply_registry()
        if registry is None:
            return None
        return registry.get(name)

    def _track(self, task: asyncio.Task[None]) -> None:
        """Сохраняет ссылку на task до его завершения (защита от GC)."""
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _run_and_publish(
        self, request: InvocationRequest, channel: InvocationReplyChannel | None
    ) -> None:
        response = await self._invoke_sync(request)
        # SYNC уже корректно ловит исключения; нам остаётся только
        # пробросить результат в reply-канал (если он есть).
        response = InvocationResponse(
            invocation_id=response.invocation_id,
            status=response.status,
            result=response.result,
            error=response.error,
            mode=request.mode,
            metadata=dict(request.metadata),
        )
        if channel is None:
            logger.warning(
                "ASYNC_API: reply_channel не найден (id=%s)", request.invocation_id
            )
            return
        try:
            await channel.send(response)
        except Exception as _:
            logger.exception("ReplyChannel.send failed (id=%s)", request.invocation_id)

    async def _run_silent(self, request: InvocationRequest) -> None:
        try:
            command = ActionCommandSchema(
                action=request.action, payload=request.payload
            )
            await self._dispatch(command, self._build_context(request))
        except Exception as _:
            logger.exception(
                "BACKGROUND task failed: action=%s id=%s",
                request.action,
                request.invocation_id,
            )

    async def _run_and_stream(
        self, request: InvocationRequest, channel: InvocationReplyChannel
    ) -> None:
        """Стримит yield'ы action'а в reply-канал по одному InvocationResponse (W22 F.2 A3).

        Middleware-цепочка применяется через :meth:`_dispatch` — audit /
        rate-limit видят STREAMING-вызов так же, как SYNC.
        """
        meta = dict(request.metadata)
        try:
            command = ActionCommandSchema(
                action=request.action, payload=request.payload
            )
            result = await self._dispatch(command, self._build_context(request))
        except KeyError as exc:
            await channel.send(
                InvocationResponse(
                    invocation_id=request.invocation_id,
                    status=InvocationStatus.ERROR,
                    error=f"Action not registered: {exc}",
                    mode=request.mode,
                    metadata=meta,
                )
            )
            return
        except Exception as exc:
            logger.exception(
                "STREAMING dispatch failed: action=%s id=%s",
                request.action,
                request.invocation_id,
            )
            await channel.send(
                InvocationResponse(
                    invocation_id=request.invocation_id,
                    status=InvocationStatus.ERROR,
                    error=str(exc)[:500],
                    mode=request.mode,
                    metadata=meta,
                )
            )
            return

        if not _is_async_iterator(result):
            # Action не stream-friendly — отправляем единичный финальный
            # ответ, чтобы клиент не висел в ожидании chunks.
            await channel.send(
                InvocationResponse(
                    invocation_id=request.invocation_id,
                    status=InvocationStatus.OK,
                    result=result,
                    mode=request.mode,
                    metadata=meta,
                )
            )
            return

        async for chunk in result:
            await channel.send(
                InvocationResponse(
                    invocation_id=request.invocation_id,
                    status=InvocationStatus.OK,
                    result=chunk,
                    mode=request.mode,
                    metadata=meta,
                )
            )
