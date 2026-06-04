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

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

from src.backend.core.di import app_state_singleton
from src.backend.core.di.dependencies import get_reply_registry_singleton
from src.backend.core.interfaces.action_dispatcher import (
    ActionDispatcher,
    DispatchContext,
)
from src.backend.core.interfaces.invocation_reply import (
    InvocationReplyChannel,
    ReplyChannelKind,
    ReplyChannelRegistryProtocol,
)
from src.backend.core.interfaces.invoker import (
    InvocationMode,
    InvocationRequest,
    InvocationResponse,
    InvocationStatus,
)
from src.backend.core.interfaces.invoker import Invoker as InvokerProtocol
from src.backend.core.types.invocation_command import ActionCommandSchema
from src.backend.core.utils.task_registry import get_task_registry
from src.backend.services.execution.action_dispatcher import get_action_dispatcher

__all__ = ("InvocationMode", "Invoker", "get_invoker")

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

    async def _dispatch(
        self, command: ActionCommandSchema, context: DispatchContext
    ) -> Any:
        """Прокси к dispatcher.dispatch с проброшенным DispatchContext.

        Контекст пробрасывается keyword-аргументом, чтобы legacy-моки в
        тестах (без kwarg ``context``) могли быть совместимы — для них
        делается fallback на однопозиционный вызов.
        """
        try:
            return await self._dispatcher.dispatch(command, context=context)
        except TypeError:
            # Legacy ActionDispatcher Protocol (без context-параметра) —
            # вызываем без context, теряем middleware-цепочку только в
            # этом узком сценарии (тесты/устаревшие реализации).
            return await self._dispatcher.dispatch(command)

    @staticmethod
    def _build_context(request: InvocationRequest) -> DispatchContext:
        """Строит :class:`DispatchContext` из :class:`InvocationRequest` (W22 F.2 A1).

        Поля контекста:
        * ``correlation_id`` берётся из request.correlation_id (если задан).
        * ``source`` = ``"invoker"`` — обозначает, что вызов инициирован
          через Invoker Gateway (а не напрямую транспортом).
        * ``attributes`` дополнительно несут ``invocation_id`` и
          ``invocation_mode`` для middleware (audit/idempotency).
        """
        attrs: dict[str, Any] = {
            "invocation_id": request.invocation_id,
            "invocation_mode": request.mode.value,
        }
        if request.metadata:
            attrs["request_metadata"] = dict(request.metadata)
        return DispatchContext(
            correlation_id=request.correlation_id, source="invoker", attributes=attrs
        )

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
            case InvocationMode.DEFERRED:
                return self._invoke_deferred(request)
            case InvocationMode.ASYNC_QUEUE:
                return await self._invoke_async_queue(request)

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
                    "STREAMING требует доступного reply_channel (по умолчанию 'ws')"
                ),
                mode=request.mode,
            )
        task = get_task_registry().create_task(
            self._run_and_stream(request, channel),
            name=f"invoker:streaming:{request.invocation_id}",
        )
        self._track(task)
        return InvocationResponse(
            invocation_id=request.invocation_id,
            status=InvocationStatus.ACCEPTED,
            mode=request.mode,
        )

    def _invoke_deferred(self, request: InvocationRequest) -> InvocationResponse:
        """Планирует однократный запуск через APScheduler.

        Время старта определяется одним из полей ``request.metadata``:

        * ``run_at``: ISO-datetime (UTC, e.g. ``2026-04-30T12:00:00+00:00``);
        * ``delay_seconds``: число — относительная задержка в секундах.

        Хранилище задач — SQLAlchemy jobstore (durable: переживает рестарт
        сервиса). Если SQLAlchemy недоступен (например, dev_light без
        синхронного движка) — fallback на in-memory ``backup`` jobstore
        с предупреждением; в этом случае задача не durable.

        ``request.metadata['deferred_durable']`` может явно отключить
        durable-режим (``False`` → ``backup`` jobstore без warning).
        """
        run_at = self._resolve_deferred_run_at(request)
        if run_at is None:
            return InvocationResponse(
                invocation_id=request.invocation_id,
                status=InvocationStatus.ERROR,
                error=(
                    "DEFERRED требует metadata.run_at (ISO datetime) или "
                    "metadata.delay_seconds (число)"
                ),
                mode=request.mode,
                metadata=dict(request.metadata),
            )

        try:
            from apscheduler.triggers.date import DateTrigger

            from src.backend.core.di.providers import get_scheduler_manager_provider

            scheduler_manager = get_scheduler_manager_provider()
        except Exception as exc:
            logger.exception("DEFERRED: APScheduler недоступен")
            return InvocationResponse(
                invocation_id=request.invocation_id,
                status=InvocationStatus.ERROR,
                error=f"APScheduler unavailable: {exc}",
                mode=request.mode,
                metadata=dict(request.metadata),
            )

        jobstore, durable = self._select_deferred_jobstore(request)
        job_id = f"deferred_invocation_{request.invocation_id}"
        try:
            scheduler_manager.scheduler.add_job(
                _run_deferred_job,
                trigger=DateTrigger(run_date=run_at),
                kwargs={"request": request},
                id=job_id,
                replace_existing=False,
                executor="async",
                jobstore=jobstore,
            )
        except Exception as exc:
            # SQLAlchemy недоступен (dev_light без sync engine) или
            # request не picklable — fallback на memory-jobstore.
            if jobstore != "backup":
                logger.warning(
                    "DEFERRED: durable jobstore недоступен (%s); "
                    "fallback на memory (id=%s)",
                    exc,
                    request.invocation_id,
                )
                scheduler_manager.scheduler.add_job(
                    _run_deferred_job,
                    trigger=DateTrigger(run_date=run_at),
                    kwargs={"request": request},
                    id=job_id,
                    replace_existing=False,
                    executor="async",
                    jobstore="backup",
                )
                durable = False
            else:
                raise
        meta = dict(request.metadata)
        meta["scheduled_at"] = run_at.isoformat()
        meta["scheduler_job_id"] = job_id
        meta["deferred_durable"] = durable
        return InvocationResponse(
            invocation_id=request.invocation_id,
            status=InvocationStatus.ACCEPTED,
            mode=request.mode,
            metadata=meta,
        )

    @staticmethod
    def _select_deferred_jobstore(request: InvocationRequest) -> tuple[str, bool]:
        """Возвращает имя jobstore и флаг durability.

        ``metadata['deferred_durable']``:

        * ``True`` (default) → SQLAlchemy ``default`` jobstore;
        * ``False`` → memory ``backup`` jobstore (для тестов/short-lived).
        """
        durable_raw = (request.metadata or {}).get("deferred_durable", True)
        durable = bool(durable_raw)
        return ("default" if durable else "backup", durable)

    def _resolve_deferred_run_at(self, request: InvocationRequest) -> datetime | None:
        meta = request.metadata or {}
        run_at_raw = meta.get("run_at")
        if isinstance(run_at_raw, datetime):
            return run_at_raw if run_at_raw.tzinfo else run_at_raw.replace(tzinfo=UTC)
        if isinstance(run_at_raw, str) and run_at_raw:
            try:
                parsed = datetime.fromisoformat(run_at_raw)
            except ValueError:
                logger.warning("DEFERRED: невалидный run_at=%r", run_at_raw)
                return None
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)

        delay_raw = meta.get("delay_seconds")
        if isinstance(delay_raw, (int, float)) and delay_raw >= 0:
            return datetime.now(UTC) + timedelta(seconds=float(delay_raw))
        return None

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


def _is_async_iterator(obj: Any) -> bool:
    """True если ``obj`` поддерживает ``async for`` (AsyncIterable/Iterator)."""
    return (hasattr(obj, "__aiter__") and isinstance(obj, AsyncIterator)) or hasattr(
        obj, "__aiter__"
    )


def _serialize_request(request: InvocationRequest) -> dict[str, Any]:
    """Сериализует :class:`InvocationRequest` в JSON-friendly dict.

    Используется FastStream-subscribers (RabbitMQ/Redis) для cross-process
    передачи; consumer восстанавливает request через
    :func:`_deserialize_request` и вызывает :class:`Invoker`.
    """
    return {
        "action": request.action,
        "payload": dict(request.payload),
        "mode": request.mode.value,
        "reply_channel": request.reply_channel,
        "invocation_id": request.invocation_id,
        "created_at": request.created_at.isoformat(),
        "metadata": dict(request.metadata),
        "timeout": request.timeout,
        "correlation_id": request.correlation_id,
    }


def _deserialize_request(raw: dict[str, Any]) -> InvocationRequest:
    """Восстанавливает :class:`InvocationRequest` из словаря."""
    created_at_raw = raw.get("created_at")
    if isinstance(created_at_raw, str):
        created_at = datetime.fromisoformat(created_at_raw)
    else:
        created_at = datetime.now(UTC)
    mode_raw = raw.get("mode") or InvocationMode.SYNC.value
    timeout_raw = raw.get("timeout")
    timeout = float(timeout_raw) if isinstance(timeout_raw, (int, float)) else None
    return InvocationRequest(
        action=str(raw["action"]),
        payload=dict(raw.get("payload") or {}),
        mode=InvocationMode(mode_raw),
        reply_channel=raw.get("reply_channel"),
        invocation_id=str(raw.get("invocation_id") or ""),
        created_at=created_at,
        metadata=dict(raw.get("metadata") or {}),
        timeout=timeout,
        correlation_id=raw.get("correlation_id"),
    )


async def _run_deferred_job(request: InvocationRequest) -> None:
    """APScheduler-job: вызывает Invoker SYNC и публикует ответ в reply_channel.

    Запускается планировщиком через :class:`DateTrigger`. Использует тот
    же мостик, что и ``_invoke_async_api`` — выполняет SYNC и пушит
    результат в reply-канал, указанный в ``request.reply_channel``
    (по умолчанию ``api``).
    """
    # Создание Invoker через app_state_singleton: если app.state есть —
    # переиспользует тот же экземпляр; иначе локальный fallback.
    invoker = get_invoker()
    sync_request = InvocationRequest(
        action=request.action,
        payload=dict(request.payload),
        mode=InvocationMode.SYNC,
        reply_channel=request.reply_channel,
        invocation_id=request.invocation_id,
        created_at=request.created_at,
        metadata=dict(request.metadata),
    )
    response = await invoker._invoke_sync(sync_request)
    response = InvocationResponse(
        invocation_id=response.invocation_id,
        status=response.status,
        result=response.result,
        error=response.error,
        mode=InvocationMode.DEFERRED,
        metadata=dict(request.metadata),
    )
    channel_kind = request.reply_channel or ReplyChannelKind.API.value
    channel = invoker._resolve_channel(channel_kind)
    if channel is None:
        logger.warning(
            "DEFERRED: reply_channel=%r не найден (invocation_id=%s)",
            channel_kind,
            request.invocation_id,
        )
        return
    try:
        await channel.send(response)
    except Exception as _:
        logger.exception(
            "DEFERRED: ReplyChannel.send failed (invocation_id=%s)",
            request.invocation_id,
        )


@app_state_singleton("invoker", factory=Invoker)
def get_invoker() -> Invoker:
    """Singleton-доступ к Invoker'у (для DI и DSL processors).

    Сначала ищет инстанс в ``app.state.invoker`` (composition root в
    :func:`src.plugins.composition.di.register_app_state`);
    для non-request контекстов lazy-создаёт через factory ``Invoker()``.
    Тело перезаписывается декоратором; ``raise`` — для mypy.
    """
    raise RuntimeError("get_invoker overridden by app_state_singleton")
