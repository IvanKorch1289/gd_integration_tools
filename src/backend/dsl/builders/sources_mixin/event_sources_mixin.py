"""FW2: EventBus source registration для RouteBuilder.

Generic ``from_event_subscribe`` — закрывает gap из docs/dsl/EVENT_SOURCES.md:
> "Нет DSL-шага для подписки на произвольный канал EventBus и
> yielding events в pipeline".

Pre-FW2: единственные DSL-источники для cross-route events:
- ``email_trigger`` (channel-specific)
- ``cdc_capture`` (CDC-specific)
- ``mq_source`` (Kafka/RabbitMQ/NATS — но требует broker)

Post-FW2: ``from_event_subscribe(channel=..., consumer_group=...)``
подписывается на in-process EventBus (Redis pub/sub или in-memory)
и yields события как Exchange messages в pipeline. Опциональный
``filter`` (callable) для selective consumption.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.backend.dsl.builders.base import RouteBuilder


class EventSourcesMixin:
    """EventBus source registration для RouteBuilder. FW2."""

    __slots__ = ()

    @classmethod
    def from_event_subscribe(
        cls,
        route_id: str,
        channel: str,
        *,
        consumer_group: str | None = None,
        filter: Callable[[Any], bool] | None = None,
        **kwargs: Any,
    ) -> RouteBuilder:
        """Создаёт маршрут с источником EventBus (Redis pub/sub).

        Лениво импортирует :class:`EventBus` из
        ``infrastructure.clients.messaging.event_bus``. Подписка
        регистрируется при route startup (см.
        ``plugins.composition.lifecycle.start_event_sources``).

        Args:
            route_id: Уникальный ID маршрута.
            channel: Имя EventBus-канала (e.g., ``events.orders``,
                ``events.user_signup``).
            consumer_group: Опциональное имя consumer group для
                load-balancing между несколькими consumers (Redis
                Streams semantics). ``None`` = broadcast.
            filter: Опциональный callable (event) -> bool для selective
                consumption. Полезно для routing одного канала в
                несколько route'ов с разными фильтрами.
            **kwargs: Дополнительные параметры (e.g., ``start_from_last``
                для offset, ``dedupe_id_field`` для идемпотентности).

        Returns:
            RouteBuilder с ``source`` установленным в
            ``event_subscribe:<channel>``.

        Example::

            route = (
                RouteBuilder.from_event_subscribe(
                    "orders.notify_slack",
                    channel="events.orders",
                    filter=lambda e: e.get("status") == "completed",
                )
                .dispatch_action("slack.post_message")
                .build()
            )

        Notes:
        - При ``consumer_group=None`` все consumers получают все
          события (Redis pub/sub). При ``consumer_group="..."``
          события распределяются между consumers в группе.
        - Фильтрация на стороне consumer'а (post-receive) — для
          server-side filtering нужен отдельный ``filter()`` processor.

        """
        if not channel:
            raise ValueError("from_event_subscribe: channel is required")

        builder: RouteBuilder = cls(
            route_id=route_id, source=f"event_subscribe:{channel}",
        )
        # Сохраняем конфиг для последующей регистрации в
        # ``infrastructure.clients.messaging.event_bus.subscribe()``
        # при route startup. См. lifecycle.start_event_sources.
        object.__setattr__(
            builder,
            "_source_config",
            {
                "type": "event_subscribe",
                "channel": channel,
                "consumer_group": consumer_group,
                "filter": filter,
                **kwargs,
            },
        )
        return builder
