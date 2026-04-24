"""Event Bus через FastStream — async pub/sub поверх Redis."""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel

__all__ = (
    "OrderEvent",
    "PipelineEvent",
    "FlagEvent",
    "RouteEvent",
    "EventBus",
    "get_event_bus",
)

logger = logging.getLogger(__name__)


# ────────────────── Event Models ──────────────────


class OrderEvent(BaseModel):
    order_id: int
    action: str
    payload: dict[str, Any] = {}


class PipelineEvent(BaseModel):
    route_id: str
    status: str
    correlation_id: str
    duration_ms: float | None = None


class FlagEvent(BaseModel):
    name: str
    enabled: bool


class RouteEvent(BaseModel):
    route_id: str
    action: str


# ────────────────── Event Bus ──────────────────


class EventBus:
    """Pub/sub event bus через FastStream Redis broker.

    Каналы:
    - events.orders — order.created, order.updated, order.completed
    - events.pipeline — pipeline.started, pipeline.completed, pipeline.failed
    - events.flags — feature_flag.toggled
    - events.routes — route.registered, route.removed
    """

    def __init__(self) -> None:
        self._broker: Any = None
        self._started = False

    async def start(self, redis_url: str = "redis://localhost:6379") -> None:
        """Запускает FastStream Redis broker."""
        from faststream.redis import RedisBroker

        self._broker = RedisBroker(redis_url)
        await self._broker.start()
        self._started = True
        logger.info("EventBus started (FastStream Redis)")

    async def stop(self) -> None:
        """Останавливает broker."""
        if self._broker:
            await self._broker.close()
            self._started = False
            logger.info("EventBus stopped")

    async def publish(self, channel: str, event: BaseModel) -> None:
        """Публикует событие в канал."""
        if not self._broker or not self._started:
            logger.warning("EventBus not started, skipping publish to %s", channel)
            return

        await self._broker.publish(event.model_dump(), channel=channel)
        logger.debug("Published to %s: %s", channel, event.__class__.__name__)

    async def publish_order_event(
        self, order_id: int, action: str, payload: dict[str, Any] | None = None
    ) -> None:
        await self.publish(
            "events.orders",
            OrderEvent(order_id=order_id, action=action, payload=payload or {}),
        )

    async def publish_pipeline_event(
        self,
        route_id: str,
        status_: str,
        correlation_id: str,
        duration_ms: float | None = None,
    ) -> None:
        await self.publish(
            "events.pipeline",
            PipelineEvent(
                route_id=route_id,
                status=status_,
                correlation_id=correlation_id,
                duration_ms=duration_ms,
            ),
        )

    async def publish_flag_event(self, name: str, enabled: bool) -> None:
        await self.publish(
            "events.flags", FlagEvent(name=name, enabled=enabled)
        )

    async def publish_route_event(self, route_id: str, action: str) -> None:
        await self.publish(
            "events.routes", RouteEvent(route_id=route_id, action=action)
        )

    async def request(
        self,
        channel: str,
        payload: dict[str, Any],
        *,
        timeout: float = 30.0,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        """Request-Reply поверх EventBus (Wave 3.3).

        Публикует ``payload`` в ``channel`` и ждёт ответа
        в ``events.replies.<correlation_id>`` не дольше ``timeout``
        секунд. Возвращает payload ответа.

        Делегирует в :class:`ReplyChannel` — вся логика future-ов
        и subscription-ов живёт там.
        """
        from app.infrastructure.clients.messaging.reply_channel import ReplyChannel

        return await ReplyChannel.instance(self).request(
            target_channel=channel,
            payload=payload,
            timeout=timeout,
            correlation_id=correlation_id,
        )


from src.infrastructure.application.di import app_state_singleton


@app_state_singleton("event_bus", EventBus)
def get_event_bus() -> EventBus:
    """Возвращает singleton EventBus."""
