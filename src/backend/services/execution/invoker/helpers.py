from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from src.backend.core.interfaces.invocation_reply import ReplyChannelKind
from src.backend.core.interfaces.invoker import (
    InvocationMode,
    InvocationRequest,
    InvocationResponse,
)
from src.backend.core.logging import get_logger

if TYPE_CHECKING:
    from src.backend.services.execution.invoker.invoker import Invoker

_logger = get_logger("services.execution.invoker")


def _is_async_iterator(obj: Any) -> bool:
    """True если ``obj`` поддерживает ``async for`` (AsyncIterable/Iterator)."""
    return (hasattr(obj, "__aiter__") and isinstance(obj, AsyncIterator)) or hasattr(
        obj, "__aiter__"
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
        _logger.warning(
            "DEFERRED: reply_channel=%r не найден (invocation_id=%s)",
            channel_kind,
            request.invocation_id,
        )
        return
    try:
        await channel.send(response)
    except Exception as _:
        _logger.exception(
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
