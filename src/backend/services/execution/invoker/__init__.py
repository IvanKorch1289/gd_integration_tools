"""Invoker package (S54 W3 decomp from invoker.py 666 LOC).

20 methods decomposed в 4 mixin files:
- ``invoke_modes_mixin.py`` (3): sync, async_api, background invocation
- ``deferred_mixin.py`` (4): streaming, deferred (jobstore + scheduled)
- ``temporal_mixin.py`` (3): async queue, Temporal adapter, Temporal activity
- ``run_mixin.py`` (5): run helpers (channel, tracking, publish, silent, streaming)

Core (__init__ + _resolve_reply_registry + _dispatch + _build_context + invoke) остается в __init__.py.

Backward-compat: ``from src.backend.services.execution.invoker import Invoker`` works.
"""

from __future__ import annotations

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

__all__ = (('Invoker', 'get_invoker', "InvocationMode"),)



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


logger = get_logger(__name__)

class Invoker(
    InvokeModesMixin,
    DeferredMixin,
    TemporalMixin,
    RunMixin,
):
    """Action invoker (4 mixins = 15 methods + 5 core)."""

    __slots__ = ()

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

def get_invoker() -> Invoker:
    """Singleton-доступ к Invoker'у (для DI и DSL processors).

    Сначала ищет инстанс в ``app.state.invoker`` (composition root в
    :func:`src.plugins.composition.di.register_app_state`);
    для non-request контекстов lazy-создаёт через factory ``Invoker()``.
    Тело перезаписывается декоратором; ``raise`` — для mypy.
    """
    raise RuntimeError("get_invoker overridden by app_state_singleton")

