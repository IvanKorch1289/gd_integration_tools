"""Реализация Invoker (W22.1 + W22.2/W22.3 расширения).

Поддерживает четыре режима из шести:

* :attr:`InvocationMode.SYNC` — блокирующий вызов через ActionDispatcher.
* :attr:`InvocationMode.ASYNC_API` — fire-and-forget, результат
  публикуется в polling-канал (:class:`MemoryReplyChannel`); клиент
  опрашивает ``GET /api/v1/invocations/{id}``.
* :attr:`InvocationMode.BACKGROUND` — fire-and-forget без отслеживания
  результата.
* :attr:`InvocationMode.STREAMING` — action возвращает ``AsyncIterator``;
  каждый yield пушится в :class:`WsReplyChannel` для зарегистрированного
  invocation_id. Завершение stream'а — закрытие WS со стороны клиента.

Режимы :attr:`InvocationMode.ASYNC_QUEUE` (требует TaskIQ) и
:attr:`InvocationMode.DEFERRED` (требует APScheduler) — пока заглушки
с ``status=ERROR``; будут реализованы в W22 продолжении.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, AsyncIterator

from src.core.di import app_state_singleton
from src.core.di.dependencies import get_reply_registry_singleton
from src.core.interfaces.action_dispatcher import ActionDispatcher
from src.core.interfaces.invocation_reply import (
    InvocationReplyChannel,
    ReplyChannelKind,
    ReplyChannelRegistryProtocol,
)
from src.core.interfaces.invoker import (
    InvocationMode,
    InvocationRequest,
    InvocationResponse,
    InvocationStatus,
)
from src.core.interfaces.invoker import Invoker as InvokerProtocol
from src.core.types.invocation_command import ActionCommandSchema
from src.services.execution.action_dispatcher import get_action_dispatcher

__all__ = ("Invoker", "InvocationMode", "get_invoker")

logger = logging.getLogger("services.execution.invoker")


class Invoker(InvokerProtocol):
    """Каркасная реализация Invoker (4 рабочих режима + 2 заглушки)."""

    def __init__(
        self,
        dispatcher: ActionDispatcher | None = None,
        *,
        reply_registry: ReplyChannelRegistryProtocol | None = None,
    ) -> None:
        self._dispatcher = dispatcher or get_action_dispatcher()
        # ReplyChannelRegistry инжектится опционально; lazy-резолв
        # из app.state через core/di сохраняет совместимость с
        # вызывающими, которые передавали только dispatcher (тесты).
        self._reply_registry_override = reply_registry
        # Активные fire-and-forget tasks хранятся, чтобы их не собрал GC
        # до завершения; auto-cleanup на done.
        self._tasks: set[asyncio.Task[None]] = set()

    def _resolve_reply_registry(self) -> ReplyChannelRegistryProtocol | None:
        if self._reply_registry_override is not None:
            return self._reply_registry_override
        try:
            return get_reply_registry_singleton()
        except RuntimeError:
            return None

    async def invoke(self, request: InvocationRequest) -> InvocationResponse:
        match request.mode:
            case InvocationMode.SYNC:
                return await self._invoke_sync(request)
            case InvocationMode.ASYNC_API:
                return self._invoke_async_api(request)
            case InvocationMode.BACKGROUND:
                return self._invoke_background(request)
            case InvocationMode.STREAMING:
                return self._invoke_streaming(request)
            case InvocationMode.ASYNC_QUEUE | InvocationMode.DEFERRED:
                return InvocationResponse(
                    invocation_id=request.invocation_id,
                    status=InvocationStatus.ERROR,
                    error=(
                        f"Mode '{request.mode.value}' is not yet implemented "
                        "(requires TaskIQ/APScheduler integration)"
                    ),
                    mode=request.mode,
                )

    async def _invoke_sync(self, request: InvocationRequest) -> InvocationResponse:
        try:
            command = ActionCommandSchema(action=request.action, payload=request.payload)
            result: Any = await self._dispatcher.dispatch(command)
            return InvocationResponse(
                invocation_id=request.invocation_id,
                status=InvocationStatus.OK,
                result=result,
                mode=request.mode,
            )
        except KeyError as exc:
            return InvocationResponse(
                invocation_id=request.invocation_id,
                status=InvocationStatus.ERROR,
                error=f"Action not registered: {exc}",
                mode=request.mode,
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
            )

    def _invoke_async_api(self, request: InvocationRequest) -> InvocationResponse:
        """Запускает action в фоновом task'е и публикует результат в polling-канал."""
        channel = self._resolve_channel(
            request.reply_channel or ReplyChannelKind.API.value
        )
        task = asyncio.create_task(self._run_and_publish(request, channel))
        self._track(task)
        return InvocationResponse(
            invocation_id=request.invocation_id,
            status=InvocationStatus.ACCEPTED,
            mode=request.mode,
        )

    def _invoke_background(self, request: InvocationRequest) -> InvocationResponse:
        """Fire-and-forget без сохранения результата."""
        task = asyncio.create_task(self._run_silent(request))
        self._track(task)
        return InvocationResponse(
            invocation_id=request.invocation_id,
            status=InvocationStatus.ACCEPTED,
            mode=request.mode,
        )

    def _invoke_streaming(self, request: InvocationRequest) -> InvocationResponse:
        """Запускает streaming action; каждый yield пушится в WS-канал."""
        channel = self._resolve_channel(
            request.reply_channel or ReplyChannelKind.WS.value
        )
        if channel is None:
            return InvocationResponse(
                invocation_id=request.invocation_id,
                status=InvocationStatus.ERROR,
                error=(
                    "STREAMING требует доступного reply_channel "
                    "(по умолчанию 'ws')"
                ),
                mode=request.mode,
            )
        task = asyncio.create_task(self._run_and_stream(request, channel))
        self._track(task)
        return InvocationResponse(
            invocation_id=request.invocation_id,
            status=InvocationStatus.ACCEPTED,
            mode=request.mode,
        )

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
        self,
        request: InvocationRequest,
        channel: InvocationReplyChannel | None,
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
        )
        if channel is None:
            logger.warning(
                "ASYNC_API: reply_channel не найден (id=%s)", request.invocation_id
            )
            return
        try:
            await channel.send(response)
        except Exception:  # noqa: BLE001
            logger.exception(
                "ReplyChannel.send failed (id=%s)", request.invocation_id
            )

    async def _run_silent(self, request: InvocationRequest) -> None:
        try:
            command = ActionCommandSchema(action=request.action, payload=request.payload)
            await self._dispatcher.dispatch(command)
        except Exception:  # noqa: BLE001
            logger.exception(
                "BACKGROUND task failed: action=%s id=%s",
                request.action,
                request.invocation_id,
            )

    async def _run_and_stream(
        self,
        request: InvocationRequest,
        channel: InvocationReplyChannel,
    ) -> None:
        """Стримит yield'ы action'а в reply-канал по одному InvocationResponse."""
        try:
            command = ActionCommandSchema(action=request.action, payload=request.payload)
            result = await self._dispatcher.dispatch(command)
        except KeyError as exc:
            await channel.send(
                InvocationResponse(
                    invocation_id=request.invocation_id,
                    status=InvocationStatus.ERROR,
                    error=f"Action not registered: {exc}",
                    mode=request.mode,
                )
            )
            return
        except Exception as exc:  # noqa: BLE001
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
                )
            )


def _is_async_iterator(obj: Any) -> bool:
    """True если ``obj`` поддерживает ``async for`` (AsyncIterable/Iterator)."""
    return hasattr(obj, "__aiter__") and isinstance(obj, AsyncIterator) or hasattr(
        obj, "__aiter__"
    )


@app_state_singleton("invoker", factory=Invoker)
def get_invoker() -> Invoker:
    """Singleton-доступ к Invoker'у (для DI и DSL processors).

    Сначала ищет инстанс в ``app.state.invoker`` (composition root в
    :func:`src.infrastructure.application.di.register_app_state`);
    для non-request контекстов lazy-создаёт через factory ``Invoker()``.
    Тело перезаписывается декоратором; ``raise`` — для mypy.
    """
    raise RuntimeError("get_invoker overridden by app_state_singleton")
