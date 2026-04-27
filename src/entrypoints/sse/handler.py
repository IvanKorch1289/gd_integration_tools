"""Server-Sent Events (SSE) endpoint.

Предоставляет однонаправленный стриминг событий
сервер→клиент через HTTP. Сервисы публикуют события
через ``event_bus``, SSE стримит их подключённым клиентам.
"""

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Request
from starlette.responses import StreamingResponse

__all__ = ("sse_router", "event_bus")

logger = logging.getLogger(__name__)

sse_router = APIRouter(prefix="/events", tags=["SSE"])


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

    async def event_generator():
        """Генератор SSE-событий."""
        try:
            while True:
                if await request.is_disconnected():
                    break

                try:
                    event = await asyncio.wait_for(queue.get(), timeout=30.0)
                    import json

                    event_type = event.get("event", "message")
                    data = json.dumps(event.get("data"), ensure_ascii=False)
                    yield f"event: {event_type}\ndata: {data}\n\n"
                except asyncio.TimeoutError:
                    # Heartbeat для поддержания соединения
                    yield ": heartbeat\n\n"
        finally:
            event_bus.unsubscribe(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
