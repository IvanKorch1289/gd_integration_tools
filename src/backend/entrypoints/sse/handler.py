"""Server-Sent Events (SSE) endpoint.

Предоставляет:

* ``GET /events/stream`` — однонаправленный pub/sub-стриминг событий
  сервер→клиент через ``event_bus`` (исторический endpoint).
* ``POST /events/invoke`` — Wave 1.5: однократный вызов action через
  :class:`ActionGatewayDispatcher` (с DSL fallback Tier 3) с ответом
  в SSE-формате (start → result/error → end). Симметрично
  WS/Webhook/Express.
"""

import asyncio
import datetime
from enum import Enum
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from starlette.responses import StreamingResponse

from src.backend.core.logging import get_logger
from src.backend.core.serialization.msgspec_hotpath import encode_json_str
from src.backend.entrypoints._action_bridge import dispatch_action_or_dsl

__all__ = ("event_bus", "sse_router")

logger = get_logger(__name__)

sse_router = APIRouter(prefix="/events", tags=["SSE"])


def _to_primitive(value: Any) -> Any:
    """Приводит value к JSON-сериализуемым примитивам (BaseModel → dict)."""
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, datetime.datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, list):
        return [_to_primitive(v) for v in value]
    if isinstance(value, dict):
        return {k: _to_primitive(v) for k, v in value.items()}
    return value


class EventBus:
    """Внутренняя шина событий для SSE.

    Сервисы публикуют события через ``publish()``,
    SSE-обработчик подписывается через ``subscribe()``.
    """

    def __init__(self) -> None:
        self._subscribers: list[asyncio.Queue[dict[str, Any]]] = []

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        """Создаёт подписку на события.

        Returns:
            Очередь, в которую будут приходить события.
        """
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=100)
        self._subscribers.append(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        """Отменяет подписку.

        Args:
            queue: Очередь подписки.
        """
        self._subscribers = [q for q in self._subscribers if q is not queue]

    async def publish(self, event_type: str, data: Any) -> None:
        """Публикует событие всем подписчикам.

        Args:
            event_type: Тип события (поле ``event`` в SSE).
            data: Данные события (сериализуются в JSON).
        """
        event = {"event": event_type, "data": data}

        for queue in list(self._subscribers):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                logger.warning("SSE очередь переполнена, событие пропущено")


event_bus = EventBus()


@sse_router.get(
    "/stream",
    summary="SSE event stream",
    description="Подключение к потоку серверных событий.",
)
async def sse_stream(request: Request) -> StreamingResponse:
    """SSE endpoint — стримит события клиенту.

    Клиент подключается через GET /events/stream и получает
    события в формате Server-Sent Events до отключения.
    """
    queue = event_bus.subscribe()

    async def _raw_generator():
        """Сырой генератор SSE-событий."""
        try:
            while True:
                if await request.is_disconnected():
                    break

                try:
                    event = await asyncio.wait_for(queue.get(), timeout=30.0)

                    event_type = event.get("event", "message")
                    data = encode_json_str(_to_primitive(event.get("data")))
                    yield f"event: {event_type}\ndata: {data}\n\n"
                except TimeoutError:
                    # Heartbeat для поддержания соединения
                    yield ": heartbeat\n\n"
        finally:
            event_bus.unsubscribe(queue)

    async def event_generator():
        """PII-aware генератор SSE-событий (S13 K1 W1).

        Оборачивает raw stream в ``stream_filter`` — applies sliding-window
        PII redaction per-tenant policy. На fail PII pipeline — прокидывает
        chunks без изменений (best-effort).
        """
        from src.backend.infrastructure.security.pii_streaming import (
            PiiStreamPolicy,
            stream_filter,
        )

        try:
            tenant_policy = getattr(request.state, "pii_streaming_policy", None)
            policy = tenant_policy if tenant_policy else PiiStreamPolicy()
            async for chunk in stream_filter(_raw_generator(), policy):
                yield chunk
        except Exception as _:
            async for chunk in _raw_generator():
                yield chunk

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


class _InvokeRequest(BaseModel):
    """Тело POST /events/invoke (Wave 1.5).

    Минимальный контракт для запуска action через SSE: имя action +
    payload. Заголовки запроса передаются в ``DispatchContext`` (через
    bridge) для сохранения correlation/idempotency.
    """

    action: str = Field(description="Имя action или DSL-маршрута.")
    payload: dict[str, Any] = Field(
        default_factory=dict, description="Полезная нагрузка вызова."
    )


@sse_router.post(
    "/invoke",
    summary="SSE invoke: однократный action → SSE response",
    description=(
        "Wave 1.5: вызывает action через ActionDispatcher (Tier 1/2) или "
        "DSL-маршрут (Tier 3) и стримит результат как SSE-события "
        "``start``, ``result``/``error``, ``end``."
    ),
)
async def sse_invoke(request: Request, body: _InvokeRequest) -> StreamingResponse:
    """Однократный action-вызов с SSE-ответом.

    Поток событий:

    1. ``event: start\\ndata: {"action": "..."}``
    2. ``event: result\\ndata: <result-json>`` или
       ``event: error\\ndata: {"code": "...", "message": "..."}``
    3. ``event: end\\ndata: {}``

    Это симметрично WS/Webhook/Express и закрывает scope Wave 1.5
    для SSE: SSE из чисто push-канала превращается также в
    request-response-канал поверх HTTP.
    """
    correlation_id = request.headers.get("x-correlation-id") or request.headers.get(
        "x-request-id"
    )
    idempotency_key = request.headers.get("idempotency-key")

    async def stream() -> Any:
        """Генератор SSE-событий: start → result|error → end."""
        yield (f"event: start\ndata: {encode_json_str({'action': body.action})}\n\n")
        try:
            bridge = await dispatch_action_or_dsl(
                action_id=body.action,
                dsl_route_id=body.action,
                payload=body.payload,
                transport="sse",
                correlation_id=correlation_id,
                idempotency_key=idempotency_key,
                attributes={"path": str(request.url.path)},
            )
        except Exception as exc:
            logger.exception("SSE invoke ошибка: %s", exc)
            err = {"code": "dispatch_failed", "message": str(exc)}
            yield f"event: error\ndata: {encode_json_str(err)}\n\n"
            yield "event: end\ndata: {}\n\n"
            return

        if bridge.success:
            payload = encode_json_str(_to_primitive(bridge.data))
            yield f"event: result\ndata: {payload}\n\n"
        else:
            err = {
                "code": bridge.error_code or "dispatch_failed",
                "message": bridge.error or "dispatch failed",
            }
            yield f"event: error\ndata: {encode_json_str(err)}\n\n"
        yield "event: end\ndata: {}\n\n"

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
