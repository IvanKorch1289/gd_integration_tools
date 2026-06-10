from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.backend.dsl.builders.base import RouteBuilder

class StreamingSourcesMixin:
    """streaming source registration (Redis Streams) для RouteBuilder. S57 W2 extraction."""

    __slots__ = ()

    @classmethod
    def from_redis_streams(
        cls, route_id: str, stream: str, consumer_group: str, **kwargs: Any
    ) -> RouteBuilder:
        """Создаёт маршрут с источником Redis Streams.

        Лениво импортирует :class:`MQSource` с transport ``redis_streams``
        из ``infrastructure.sources.mq`` (FastStream + redis-py).

        Args:
            route_id: Уникальный ID маршрута.
            stream: Имя Redis Stream (ключ).
            consumer_group: Имя consumer group (для XREADGROUP).
            **kwargs: Дополнительные параметры для :class:`MQSource`
                (connect_url, decode_json и др.).

        Returns:
            RouteBuilder с ``source`` установленным в ``redis_streams:<stream>``.

        Example::

            route = (
                RouteBuilder.from_redis_streams(
                    "audit.trail",
                    stream="audit:events",
                    consumer_group="audit-consumers",
                    connect_url="redis://redis:6379",
                )
                .dispatch_action("audit.persist")
                .build()
            )
        """
        import importlib

        mod = importlib.import_module("src.backend.infrastructure.sources.mq")
        MQSource = mod.MQSource
        source_instance = MQSource(
            source_id=route_id,
            transport="redis_streams",
            topic=stream,
            group=consumer_group,
            **kwargs,
        )
        builder: RouteBuilder = cls(route_id=route_id, source=f"redis_streams:{stream}")
        object.__setattr__(builder, "_source_instance", source_instance)
        return builder

