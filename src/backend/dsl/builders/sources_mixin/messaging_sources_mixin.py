from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.backend.dsl.builders.base import RouteBuilder

class MessagingSourcesMixin:
    """messaging source registration (Kafka, Rabbit, MQTT) для RouteBuilder. S57 W2 extraction."""

    __slots__ = ()

    @classmethod
    def from_kafka(
        cls,
        route_id: str,
        topic: str,
        bootstrap_servers: str,
        group_id: str,
        **kwargs: Any,
    ) -> RouteBuilder:
        """Создаёт маршрут с источником Apache Kafka.

        Лениво импортирует :class:`MQSource` с transport ``kafka``
        из ``infrastructure.sources.mq`` (FastStream + aiokafka).

        Args:
            route_id: Уникальный ID маршрута.
            topic: Имя Kafka-топика.
            bootstrap_servers: Kafka bootstrap servers (``host:port``).
            group_id: Consumer group ID.
            **kwargs: Дополнительные параметры для :class:`MQSource`.

        Returns:
            RouteBuilder с ``source`` установленным в ``kafka:<topic>``.

        Example::

            route = (
                RouteBuilder.from_kafka(
                    "payments.stream",
                    topic="payments",
                    bootstrap_servers="kafka:9092",
                    group_id="payments-consumer",
                )
                .dispatch_action("payments.process")
                .build()
            )
        """
        import importlib

        mod = importlib.import_module("src.backend.infrastructure.sources.mq")
        MQSource = mod.MQSource
        source_instance = MQSource(
            source_id=route_id,
            transport="kafka",
            topic=topic,
            group=group_id,
            connect_url=bootstrap_servers,
            **kwargs,
        )
        builder: RouteBuilder = cls(route_id=route_id, source=f"kafka:{topic}")
        object.__setattr__(builder, "_source_instance", source_instance)
        return builder

    @classmethod
    def from_rabbit(
        cls, route_id: str, queue: str, url: str, **kwargs: Any
    ) -> RouteBuilder:
        """Создаёт маршрут с источником RabbitMQ.

        Лениво импортирует :class:`MQSource` с transport ``rabbitmq``
        из ``infrastructure.sources.mq`` (FastStream + aio-pika).

        Args:
            route_id: Уникальный ID маршрута.
            queue: Имя очереди RabbitMQ.
            url: AMQP URL (``amqp://user:pass@host/vhost``).
            **kwargs: Дополнительные параметры для :class:`MQSource`.

        Returns:
            RouteBuilder с ``source`` установленным в ``rabbitmq:<queue>``.

        Example::

            route = (
                RouteBuilder.from_rabbit(
                    "notifications.consumer",
                    queue="notifications",
                    url="amqp://guest:guest@rabbitmq/",
                )
                .dispatch_action("notifications.process")
                .build()
            )
        """
        import importlib

        mod = importlib.import_module("src.backend.infrastructure.sources.mq")
        MQSource = mod.MQSource
        source_instance = MQSource(
            source_id=route_id,
            transport="rabbitmq",
            topic=queue,
            connect_url=url,
            **kwargs,
        )
        builder: RouteBuilder = cls(route_id=route_id, source=f"rabbitmq:{queue}")
        object.__setattr__(builder, "_source_instance", source_instance)
        return builder

    @classmethod
    def from_mqtt(
        cls, route_id: str, topic: str, broker_url: str, **kwargs: Any
    ) -> RouteBuilder:
        """Создаёт маршрут с источником MQTT.

        MQTT Source — лёгкий wrapper поверх ``aiomqtt`` (lazy-import).
        ``source`` строка: ``mqtt:<topic>``.

        Args:
            route_id: Уникальный ID маршрута.
            topic: MQTT-топик (поддерживаются wildcards: ``+``, ``#``).
            broker_url: URL брокера (``mqtt://host:1883`` или ``mqtts://host:8883``).
            **kwargs: Дополнительные параметры (qos, client_id и др.).

        Returns:
            RouteBuilder с ``source`` установленным в ``mqtt:<topic>``.

        Example::

            route = (
                RouteBuilder.from_mqtt(
                    "sensors.telemetry",
                    topic="sensors/+/temperature",
                    broker_url="mqtt://iot-broker:1883",
                )
                .dispatch_action("sensors.store_reading")
                .build()
            )
        """
        # MQTT Source-класса пока нет в infrastructure/sources/
        # — используем строковый DSN; source_instance = None (будущее расширение)
        builder: RouteBuilder = cls(route_id=route_id, source=f"mqtt:{topic}")
        # Сохраняем параметры для будущей регистрации MQTTSource
        object.__setattr__(
            builder,
            "_source_config",
            {"transport": "mqtt", "topic": topic, "broker_url": broker_url, **kwargs},
        )
        return builder

