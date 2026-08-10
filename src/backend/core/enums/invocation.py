from enum import StrEnum

__all__ = ("BrokerKind", "InvokeMode")


class InvokeMode(StrEnum):
    """
    Режим выполнения действия.

    Attributes:
        direct: Выполнить use case напрямую в рамках HTTP-запроса.
        event: Опубликовать команду в event bus.

    """

    direct = "direct"
    event = "event"


class BrokerKind(StrEnum):
    """
    Поддерживаемые типы брокеров для публикации команды.

    Attributes:
        redis: Redis Streams.
        rabbit: RabbitMQ.
        kafka: Kafka

    """

    redis = "redis"
    rabbit = "rabbit"
    kafka = "kafka"
