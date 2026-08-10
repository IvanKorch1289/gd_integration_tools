"""EventBus DSL mixin (S18 W17, V22 NEW → S173 M-2 closeout): .to_eventbus()/.from_eventbus().

Реализует chainable .to_eventbus(topic, payload_ref) и
.from_eventbus(topic_pattern, ack_mode) методы RouteBuilder через
маркер-процессоры. Реальная привязка к EventBus backend
(Kafka/RabbitMQ/NATS) — через downstream EventBusFacade в lifespan.

Sprint 173 M-2 closeout (Plan lockjaw-vision-rocket.md §Sprint 173 #2):
подключены :class:`EventBusFacade.publish` и
:meth:`EventBusFacade.subscribe_with_lifecycle` через DI-fallback
(``get_event_bus_facade()`` provider, безопасный no-op если facade
не зарегистрирован). Direct import из ``core.messaging.event_bus``
оставлен как fallback для backward compat.

Feature-flag: ``feature_flags.eventbus_dsl_enabled`` (S18 W3 backbone,
default-OFF). При OFF — маркер-процессор no-op (как policy_mixin
pattern).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.backend.dsl.builders.base import RouteBuilder

__all__ = ("EventBusMixin", "EventBusPublishProcessor", "EventBusSubscribeProcessor")


def _resolve_event_bus_facade() -> Any:
    """Получить :class:`EventBusFacade` через DI; вернуть ``None`` если нет.

    Returns:
        Экземпляр facade или ``None`` если DI-provider не зарегистрирован
        (dev_light / unit-tests без DI).
    """
    try:
        from src.backend.core.di.providers.infrastructure_locator import (
            get_event_bus_facade_provider,
        )

        return get_event_bus_facade_provider()
    except (ImportError, AttributeError, RuntimeError):
        return None


class EventBusPublishProcessor:
    """Marker-процессор для ``.to_eventbus(topic, payload_ref)`` (S18 W17 → S173).

    На исполнении публикует событие в EventBus (Kafka/RabbitMQ/NATS) через
    :meth:`EventBusFacade.publish` (Sprint 173 closeout) или fallback на
    ``core.messaging.event_bus.GenericEvent`` для backward compat.
    При feature-flag OFF — no-op маркер.
    """

    side_effect: Any = "PUBLISH"
    compensatable: bool = False

    def __init__(
        self, *, topic: str, payload_ref: str = "body", name: str | None = None,
    ) -> None:
        self.name = name or f"eventbus.publish({topic})"
        self.topic = topic
        self.payload_ref = payload_ref

    async def process(self, exchange: Any, context: Any) -> None:
        """Опубликовать событие в EventBus (S133 W4 → S173).

        Если брокер не запущен или publish не удался — fallback к записи
        в ``exchange.properties["_eventbus_published"]`` для backward compat
        и тестов без Redis.
        """
        try:
            from src.backend.core.config.features import feature_flags

            if not feature_flags.eventbus_dsl_enabled:
                return
        except Exception as _:
            return

        payload = self._resolve_payload(exchange)

        # S173 M-2: try EventBusFacade first (canonical, capability-checked),
        # fallback к direct ``core.messaging.event_bus`` для backward compat.
        facade = _resolve_event_bus_facade()
        if facade is not None:
            try:
                await facade.publish(
                    self.topic,
                    self._build_event(exchange, payload),
                )
                return
            except Exception as exc:
                # Best-effort: логируем + fallback к direct publish.
                from src.backend.core.logging import get_logger

                get_logger(__name__).warning(
                    "EventBusFacade.publish failed topic=%s, "
                    "falling back to direct publish: %s",
                    self.topic,
                    exc,
                )

        try:
            import time

            from src.backend.core.messaging.event_bus import GenericEvent, get_event_bus

            bus = get_event_bus()
            if bus._broker is None or not bus._started:
                self._mark_published(exchange, payload)
                return

            event = GenericEvent(
                topic=self.topic,
                payload=payload,
                correlation_id=exchange.properties.get("correlation_id"),
                timestamp=time.time(),
            )
            await bus.publish(self.topic, event)
        except Exception as exc:
            from src.backend.core.logging import get_logger

            get_logger(__name__).warning(
                "EventBus publish failed for topic=%s: %s", self.topic, exc,
            )
            self._mark_published(exchange, payload)

    def _build_event(self, exchange: Any, payload: Any) -> dict[str, Any]:
        """Build event payload для EventBusFacade.publish.

        EventBusFacade.publish принимает произвольный event (dict или
        объект). Формируем dict с correlation_id для downstream
        observability.

        Args:
            exchange: Текущий DSL exchange.
            payload: Resolved payload (из ``_resolve_payload``).

        Returns:
            Dict-ready event для facade.
        """
        return {
            "topic": self.topic,
            "payload": payload,
            "correlation_id": exchange.properties.get("correlation_id"),
        }

    def _resolve_payload(self, exchange: Any) -> Any:
        if self.payload_ref == "body":
            return exchange.in_message.body
        if self.payload_ref.startswith("property:"):
            return exchange.properties.get(self.payload_ref.removeprefix("property:"))
        return None

    def _mark_published(self, exchange: Any, payload: Any) -> None:
        published = list(exchange.properties.get("_eventbus_published") or [])
        published.append({"topic": self.topic, "payload": payload})
        exchange.set_property("_eventbus_published", published)

    def to_spec(self) -> dict[str, Any] | None:
        """Метод to_spec (см. signature)."""
        return {
            "eventbus_publish": {"topic": self.topic, "payload_ref": self.payload_ref},
        }


class EventBusSubscribeProcessor:
    """Marker-процессор для ``.from_eventbus(topic_pattern, ack_mode)`` (S18 W17 → S173).

    S173 M-2 closeout: реальный consumer wiring через
    :meth:`EventBusFacade.subscribe_with_lifecycle` если facade
    доступен. Если нет — fallback к metadata-декларации (как в S18).
    """

    side_effect: Any = "PURE"
    compensatable: bool = True

    def __init__(
        self, *, topic_pattern: str, ack_mode: str = "auto", name: str | None = None,
    ) -> None:
        self.name = name or f"eventbus.subscribe({topic_pattern})"
        self.topic_pattern = topic_pattern
        self.ack_mode = ack_mode

    async def process(self, exchange: Any, context: Any) -> None:
        """Записать subscription декларацию в metadata + subscribe через facade.

        S173 M-2: при наличии :class:`EventBusFacade` — реальная
        подписка через ``subscribe_with_lifecycle``. При отсутствии —
        только metadata-декларация (backward compat для unit-тестов).
        """
        try:
            from src.backend.core.config.features import feature_flags

            if not feature_flags.eventbus_dsl_enabled:
                return
        except Exception as _:
            return

        # Всегда пишем декларацию в metadata для трейсинга.
        subscriptions = list(exchange.properties.get("_eventbus_subscribed") or [])
        subscriptions.append(
            {"topic_pattern": self.topic_pattern, "ack_mode": self.ack_mode},
        )
        exchange.set_property("_eventbus_subscribed", subscriptions)

        # S173 M-2: попытка реальной подписки через facade.
        facade = _resolve_event_bus_facade()
        if facade is None:
            return
        try:
            handler = _make_eventbus_handler(
                exchange=exchange,
                context=context,
                topic_pattern=self.topic_pattern,
                ack_mode=self.ack_mode,
            )
            await facade.subscribe_with_lifecycle(
                self.topic_pattern,
                handler,
                topic_pattern=self.topic_pattern,
                ack_mode=self.ack_mode,
            )
        except Exception as exc:
            from src.backend.core.logging import get_logger

            get_logger(__name__).warning(
                "EventBusFacade.subscribe failed pattern=%s: %s "
                "(metadata declaration preserved)",
                self.topic_pattern,
                exc,
            )

    def to_spec(self) -> dict[str, Any] | None:
        """Метод to_spec (см. signature)."""
        return {
            "eventbus_subscribe": {
                "topic_pattern": self.topic_pattern,
                "ack_mode": self.ack_mode,
            },
        }


def _make_eventbus_handler(
    *,
    exchange: Any,
    context: Any,
    topic_pattern: str,
    ack_mode: str,
) -> Any:
    """Construct async handler для EventBus subscribe.

    Handler записывает полученное событие в ``exchange.properties``
    для downstream visibility. Реальная обработка (route re-trigger)
    — carryover (требует RouteBuilder infrastructure integration).

    Args:
        exchange: Текущий DSL exchange.
        context: Execution context.
        topic_pattern: Wildcard pattern подписки.
        ack_mode: ``"auto"`` / ``"manual"``.

    Returns:
        Async handler ``async (event) -> None``.
    """
    async def _handler(event: Any) -> None:
        events = list(exchange.properties.get("_eventbus_received") or [])
        events.append(
            {
                "topic_pattern": topic_pattern,
                "ack_mode": ack_mode,
                "event": event,
            },
        )
        exchange.set_property("_eventbus_received", events)

    return _handler


class EventBusMixin:
    """RouteBuilder mixin для .to_eventbus()/.from_eventbus() (S18 W17).

    Stateless: использует ``self._add`` через MRO. Контракт см. в
    :class:`RouteBuilder` base.
    """

    __slots__ = ()

    def to_eventbus(
        self, topic: str, *, payload_ref: str = "body", name: str | None = None,
    ) -> RouteBuilder:
        """Publish текущий exchange в EventBus topic (V22 NEW).

        Args:
            topic: Имя topic'а (Kafka topic / RabbitMQ exchange / NATS subject).
            payload_ref: Источник payload (``"body"`` или
                ``"property:<name>"``). Default — ``body``.
            name: Имя процессора в трейсах.
        """
        return self._add(  # type: ignore[attr-defined]
            EventBusPublishProcessor(topic=topic, payload_ref=payload_ref, name=name),
        )

    def from_eventbus(
        self, topic_pattern: str, *, ack_mode: str = "auto", name: str | None = None,
    ) -> RouteBuilder:
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
                topic_pattern=topic_pattern, ack_mode=ack_mode, name=name,
            ),
        )
