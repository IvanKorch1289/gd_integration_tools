"""EventBus DSL mixin (S18 W17, V22 NEW): .to_eventbus()/.from_eventbus().

Реализует chainable .to_eventbus(topic, payload_ref) и
.from_eventbus(topic_pattern, ack_mode) методы RouteBuilder через
маркер-процессоры. Реальная привязка к EventBus backend
(Kafka/RabbitMQ/NATS) — через downstream EventBusFacade в lifespan.

Feature-flag: ``feature_flags.eventbus_dsl_enabled`` (S18 W3 backbone,
default-OFF). При OFF — маркер-процессор no-op (как policy_mixin
pattern).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.backend.dsl.builders.base import RouteBuilder

__all__ = ("EventBusMixin", "EventBusPublishProcessor", "EventBusSubscribeProcessor")


class EventBusPublishProcessor:
    """Marker-процессор для ``.to_eventbus(topic, payload_ref)`` (S18 W17).

    На исполнении публикует событие в EventBus (Kafka/RabbitMQ/NATS) через
    EventBusFacade.publish. При feature-flag OFF — no-op маркер.
    """

    side_effect: Any = "PUBLISH"
    compensatable: bool = False

    def __init__(
        self, *, topic: str, payload_ref: str = "body", name: str | None = None
    ) -> None:
        self.name = name or f"eventbus.publish({topic})"
        self.topic = topic
        self.payload_ref = payload_ref

    async def process(self, exchange: Any, context: Any) -> None:
        """Записать публикацию в metadata (S18 W17 scaffold).

        Wiring в EventBusFacade.publish — carryover (требует backend
        registry в lifespan + correlation_id propagation в headers).
        """
        try:
            from src.backend.core.config.features import feature_flags  # noqa: PLC0415

            if not feature_flags.eventbus_dsl_enabled:
                return
        except Exception as _:  # noqa: BLE001
            return

        payload = (
            exchange.body
            if self.payload_ref == "body"
            else (
                exchange.properties.get(self.payload_ref.removeprefix("property:"))
                if self.payload_ref.startswith("property:")
                else None
            )
        )
        published = list(exchange.properties.get("_eventbus_published") or [])
        published.append({"topic": self.topic, "payload": payload})
        exchange.set_property("_eventbus_published", published)

    def to_spec(self) -> dict[str, Any] | None:
        return {
            "eventbus_publish": {"topic": self.topic, "payload_ref": self.payload_ref}
        }


class EventBusSubscribeProcessor:
    """Marker-процессор для ``.from_eventbus(topic_pattern, ack_mode)`` (S18 W17).

    Декларация subscription'а в metadata. Реальный consumer wiring
    (Kafka consumer group / RabbitMQ queue bind) — carryover (требует
    EventBusFacade.subscribe в lifespan).
    """

    side_effect: Any = "PURE"
    compensatable: bool = True

    def __init__(
        self, *, topic_pattern: str, ack_mode: str = "auto", name: str | None = None
    ) -> None:
        self.name = name or f"eventbus.subscribe({topic_pattern})"
        self.topic_pattern = topic_pattern
        self.ack_mode = ack_mode

    async def process(self, exchange: Any, context: Any) -> None:
        """Записать subscription декларацию в metadata."""
        try:
            from src.backend.core.config.features import feature_flags  # noqa: PLC0415

            if not feature_flags.eventbus_dsl_enabled:
                return
        except Exception as _:  # noqa: BLE001
            return

        subscriptions = list(exchange.properties.get("_eventbus_subscribed") or [])
        subscriptions.append(
            {"topic_pattern": self.topic_pattern, "ack_mode": self.ack_mode}
        )
        exchange.set_property("_eventbus_subscribed", subscriptions)

    def to_spec(self) -> dict[str, Any] | None:
        return {
            "eventbus_subscribe": {
                "topic_pattern": self.topic_pattern,
                "ack_mode": self.ack_mode,
            }
        }


class EventBusMixin:
    """RouteBuilder mixin для .to_eventbus()/.from_eventbus() (S18 W17).

    Stateless: использует ``self._add`` через MRO. Контракт см. в
    :class:`RouteBuilder` base.
    """

    __slots__ = ()

    def to_eventbus(
        self, topic: str, *, payload_ref: str = "body", name: str | None = None
    ) -> "RouteBuilder":
        """Publish текущий exchange в EventBus topic (V22 NEW).

        Args:
            topic: Имя topic'а (Kafka topic / RabbitMQ exchange / NATS subject).
            payload_ref: Источник payload (``"body"`` или
                ``"property:<name>"``). Default — ``body``.
            name: Имя процессора в трейсах.
        """
        return self._add(  # type: ignore[attr-defined]
            EventBusPublishProcessor(topic=topic, payload_ref=payload_ref, name=name)
        )

    def from_eventbus(
        self, topic_pattern: str, *, ack_mode: str = "auto", name: str | None = None
    ) -> "RouteBuilder":
        """Subscribe маршрут на EventBus topic_pattern (V22 NEW).

        Args:
            topic_pattern: Wildcard pattern (``"orders.*"``,
                ``"events.>"`` для NATS).
            ack_mode: ``"auto"`` (autoack) или ``"manual"`` (требует
                .ack() в pipeline).
            name: Имя процессора в трейсах.
        """
        return self._add(  # type: ignore[attr-defined]
            EventBusSubscribeProcessor(
                topic_pattern=topic_pattern, ack_mode=ack_mode, name=name
            )
        )
