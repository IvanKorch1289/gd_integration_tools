"""Event Bus через FastStream — async pub/sub поверх Redis.

S13 K3 W3: добавлен опциональный schema-validation hook через
:class:`ServiceSchemaRegistry`. Если зарегистрирована схема для канала —
publish() валидирует payload через ``jsonschema``; на fail — поднимает
:class:`EventSchemaValidationError`.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from src.backend.core.errors import BaseError
from src.backend.core.logging import get_logger

__all__ = (
    "EventBus",
    "EventSchemaValidationError",
    "FlagEvent",
    "OrderEvent",
    "PipelineEvent",
    "RouteEvent",
    "get_event_bus",
)

logger = get_logger(__name__)


class EventSchemaValidationError(BaseError):
    """Payload не соответствует зарегистрированной для канала JSON-Schema (S13 K3 W3)."""

    def __init__(self, channel: str, event_type: str, reason: str) -> None:
        super().__init__(
            f"EventBus schema validation failed for channel='{channel}', "
            f"event_type='{event_type}': {reason}"
        )
        self.channel = channel
        self.event_type = event_type
        self.reason = reason


# ────────────────── Event Models ──────────────────


class OrderEvent(BaseModel):
    """Order event payload."""

    order_id: int
    action: str
    payload: dict[str, Any] = {}


class PipelineEvent(BaseModel):
    """Pipeline execution event payload."""

    route_id: str
    status: str
    correlation_id: str
    duration_ms: float | None = None


class FlagEvent(BaseModel):
    """Feature flag change event payload."""

    name: str
    enabled: bool


class RouteEvent(BaseModel):
    """Route event payload."""

    route_id: str
    action: str


class GenericEvent(BaseModel):
    """Generic event payload for DSL EventBus publish (S133 W4).

    ponytail: minimal Pydantic model; avoids per-topic event classes
    for route-level pub/sub.
    """

    topic: str
    payload: dict[str, Any] | list[Any] | str | int | float | bool | None = None
    correlation_id: str | None = None
    timestamp: float | None = None


# ────────────────── Event Bus ──────────────────


class EventBus:
    """Pub/sub event bus через FastStream Redis broker.

    Каналы:
    - events.orders — order.created, order.updated, order.completed
    - events.pipeline — pipeline.started, pipeline.completed, pipeline.failed
    - events.flags — feature_flag.toggled
    - events.routes — route.registered, route.removed
    """

    def __init__(self, schema_registry: Any | None = None) -> None:
        self._broker: Any = None
        self._started = False
        self._schema_registry = schema_registry

    def attach_schema_registry(self, registry: Any) -> None:
        """Прикрепить :class:`ServiceSchemaRegistry` для validation-hook (S13 K3 W3)."""
        self._schema_registry = registry

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

    def _validate_event(self, channel: str, event: BaseModel) -> None:
        """Проверяет payload против зарегистрированной схемы (S13 K3 W3).

        No-op если registry отсутствует или схема не зарегистрирована —
        backward-compatible поведение.
        """
        if self._schema_registry is None:
            return
        from src.backend.services.schema_registry.registry import SchemaKind

        event_type = event.__class__.__name__
        subject = f"events.{channel}.{event_type}"
        entry = self._schema_registry.get(SchemaKind.EVENT, subject)
        if entry is None or entry.spec_schema is None:
            return
        try:
            import jsonschema

            jsonschema.validate(instance=event.model_dump(), schema=entry.spec_schema)
        except jsonschema.ValidationError as exc:  # pragma: no cover
            raise EventSchemaValidationError(
                channel=channel, event_type=event_type, reason=exc.message
            ) from exc
        except ImportError:  # pragma: no cover - jsonschema опциональный
            logger.debug("jsonschema not installed; skipping EventBus validation")

    async def publish(self, channel: str, event: BaseModel) -> None:
        """Publish event to channel.

        Validates event against registered schema if available.

        Args:
            channel: Channel name.
            event: Event to publish.

        Raises:
            EventSchemaValidationError: If schema validation fails.
        """
        self._validate_event(channel, event)

        if not self._broker or not self._started:
            logger.warning("EventBus not started, skipping publish to %s", channel)
            return

        await self._broker.publish(event.model_dump(), channel=channel)
        logger.debug("Published to %s: %s", channel, event.__class__.__name__)

    async def publish_order_event(
        self, order_id: int, action: str, payload: dict[str, Any] | None = None
    ) -> None:
        """Publish order event.

        Args:
            order_id: Order ID.
            action: Order action.
            payload: Optional event payload.
        """
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
        """Publish pipeline event.

        Args:
            route_id: Route identifier.
            status_: Pipeline status.
            correlation_id: Correlation ID.
            duration_ms: Optional duration in milliseconds.
        """
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
        """Publish feature flag event.

        Args:
            name: Feature flag name.
            enabled: New flag state.
        """
        await self.publish("events.flags", FlagEvent(name=name, enabled=enabled))

    async def publish_route_event(self, route_id: str, action: str) -> None:
        await self.publish(
            "events.routes", RouteEvent(route_id=route_id, action=action)
        )

    async def subscribe(self, channel: str, handler: Any) -> Any:
        """Sprint 12 K3 W4 — generic subscribe для reactive triggers.

        Args:
            channel: pattern / точный channel.
            handler: ``async (event: dict) -> None``.

        Returns:
            SubscriptionHandle (FastStream subscriber descriptor) или ``None``.
        """
        if not self._broker or not self._started:
            logger.warning(
                "EventBus.subscribe: broker not started, channel=%s ignored", channel
            )
            return None
        try:
            decorator = self._broker.subscriber(channel)
            decorator(handler)
        except Exception as exc:
            logger.error("EventBus.subscribe failed for %s: %s", channel, exc)
            return None
        return handler

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
        from src.backend.infrastructure.clients.messaging.reply_channel import (
            ReplyChannel,
        )

        return await ReplyChannel.instance(self).request(
            target_channel=channel,
            payload=payload,
            timeout=timeout,
            correlation_id=correlation_id,
        )


from src.backend.core.di import app_state_singleton


@app_state_singleton("event_bus", EventBus)
def get_event_bus() -> EventBus:  # type: ignore[empty-body]
    """Возвращает singleton EventBus."""
