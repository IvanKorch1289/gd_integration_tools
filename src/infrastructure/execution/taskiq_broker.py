"""TaskIQ broker и worker-task для режима ASYNC_QUEUE Invoker (W22 этап B).

Цель — иметь durable очередь для отложенного выполнения action'ов:

* В **dev_light** — :class:`taskiq.InMemoryBroker` (без внешних
  зависимостей, без durability).
* В **dev/staging/prod** — :class:`taskiq_redis.ListQueueBroker`
  (Redis Streams) с :class:`taskiq_redis.RedisAsyncResultBackend`.

Брокер выбирается через :data:`settings.taskiq.backend`
(``"memory"`` | ``"redis"``). При запуске worker'а
(``taskiq worker src.infrastructure.execution.taskiq_broker:broker``)
зарегистрированный таск :func:`run_taskiq_invocation` принимает
сериализованный :class:`InvocationRequest` и вызывает Invoker.invoke
в режиме SYNC, после чего публикует результат в указанный
``reply_channel`` (по умолчанию ``api``).

Lazy import: модуль ``taskiq`` опциональный; если не установлен —
импорт `get_broker`/`get_invocation_task` пробрасывает исключение,
которое Invoker корректно превращает в ``InvocationResponse(ERROR)``.
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover
    from taskiq import AsyncBroker, AsyncTaskiqDecoratedTask

__all__ = (
    "get_broker",
    "get_invocation_task",
    "run_taskiq_invocation",
    "broker",
)

logger = logging.getLogger("infrastructure.execution.taskiq_broker")

_broker: "AsyncBroker | None" = None
_invocation_task: "AsyncTaskiqDecoratedTask[Any, Any] | None" = None


def _resolve_backend_name() -> str:
    """Возвращает имя backend'а: memory | redis.

    Источники (в порядке приоритета):

    1. ``settings.taskiq.backend`` (если settings доступны);
    2. ``TASKIQ_BACKEND`` env-переменная;
    3. fallback ``memory`` для dev_light.
    """
    try:
        from src.core.config.settings import settings

        backend = getattr(getattr(settings, "taskiq", None), "backend", None)
        if backend:
            return str(backend)
    except Exception:  # noqa: BLE001, S110
        # Settings ещё не загружены или taskiq-секции нет — fallback на env.
        return os.getenv("TASKIQ_BACKEND", "memory").lower()
    return os.getenv("TASKIQ_BACKEND", "memory").lower()


def _resolve_redis_url() -> str:
    """URL Redis для taskiq-redis broker и result backend."""
    try:
        from src.core.config.settings import settings

        url = getattr(getattr(settings, "taskiq", None), "redis_url", None)
        if url:
            return str(url)
        redis_url = getattr(getattr(settings, "redis", None), "url", None)
        if redis_url:
            return str(redis_url)
    except Exception:  # noqa: BLE001, S110
        # Settings ещё не загружены — fallback на env-переменную.
        return os.getenv("TASKIQ_REDIS_URL", "redis://localhost:6379/0")
    return os.getenv("TASKIQ_REDIS_URL", "redis://localhost:6379/0")


def get_broker() -> "AsyncBroker":
    """Lazy singleton TaskIQ broker.

    Raises:
        ImportError: если ``taskiq`` (или ``taskiq-redis`` для backend=redis)
            не установлен.
    """
    global _broker
    if _broker is not None:
        return _broker

    backend = _resolve_backend_name()
    if backend == "redis":
        from taskiq_redis import ListQueueBroker, RedisAsyncResultBackend

        url = _resolve_redis_url()
        _broker = ListQueueBroker(url=url).with_result_backend(
            RedisAsyncResultBackend(redis_url=url)
        )
    else:
        from taskiq import InMemoryBroker

        _broker = InMemoryBroker()

    return _broker


def get_invocation_task() -> "AsyncTaskiqDecoratedTask[Any, Any]":
    """Lazy-регистрация и выдача декорированного TaskIQ-таска.

    Зарегистрирован под именем ``invoker.run`` чтобы быть стабильным
    идентификатором для worker'а (см. ``run_taskiq_invocation``).

    ``broker.task`` — декоратор-фабрика: ``broker.task(name)`` возвращает
    декоратор, который оборачивает функцию.
    """
    global _invocation_task
    if _invocation_task is not None:
        return _invocation_task
    broker_inst = get_broker()
    decorator = broker_inst.task("invoker.run")
    _invocation_task = decorator(run_taskiq_invocation)
    return _invocation_task


async def run_taskiq_invocation(raw_request: dict[str, Any]) -> dict[str, Any]:
    """Worker-side: восстанавливает Invocation и выполняет в SYNC + reply.

    Args:
        raw_request: dict от :func:`_serialize_request`.

    Returns:
        Сериализованный :class:`InvocationResponse` (для diagnostics
        worker'а; основной канал доставки — ``reply_channel``).
    """
    from src.core.interfaces.invoker import (
        InvocationMode,
        InvocationRequest,
        InvocationResponse,
        InvocationStatus,
    )
    from src.infrastructure.messaging.invocation_replies.registry import (
        get_reply_channel_registry,
    )
    from src.services.execution.invoker import Invoker, _deserialize_request

    request: InvocationRequest = _deserialize_request(raw_request)
    sync_request = InvocationRequest(
        action=request.action,
        payload=dict(request.payload),
        mode=InvocationMode.SYNC,
        reply_channel=request.reply_channel,
        invocation_id=request.invocation_id,
        created_at=request.created_at,
        metadata=dict(request.metadata),
    )
    invoker = Invoker()
    response = await invoker._invoke_sync(sync_request)

    final_response = InvocationResponse(
        invocation_id=response.invocation_id,
        status=response.status,
        result=response.result,
        error=response.error,
        mode=InvocationMode.ASYNC_QUEUE,
        metadata=dict(request.metadata),
    )

    channel_kind = request.reply_channel or "api"
    registry = get_reply_channel_registry()
    channel = registry.get(channel_kind)
    if channel is None:
        logger.warning(
            "ASYNC_QUEUE: reply_channel=%r не найден (invocation_id=%s)",
            channel_kind,
            request.invocation_id,
        )
    else:
        try:
            await channel.send(final_response)
        except Exception:  # noqa: BLE001
            logger.exception(
                "ASYNC_QUEUE: ReplyChannel.send failed (invocation_id=%s)",
                request.invocation_id,
            )

    return {
        "invocation_id": final_response.invocation_id,
        "status": final_response.status.value
        if isinstance(final_response.status, InvocationStatus)
        else str(final_response.status),
        "error": final_response.error,
    }


def broker() -> "AsyncBroker":  # noqa: D401
    """Module-level accessor for ``taskiq worker``-CLI.

    ``taskiq worker src.infrastructure.execution.taskiq_broker:broker``
    """
    return get_broker()
