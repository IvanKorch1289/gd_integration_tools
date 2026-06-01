from enum import Enum

__all__ = ("InvokeMode", "BrokerKind")


class InvokeMode(str, Enum):
    """
    Режим выполнения действия.

    Attributes:
        direct: Выполнить use case напрямую в рамках HTTP-запроса.
        event: Опубликовать команду в event bus.
    """

    direct = "direct"
    event = "event"


class BrokerKind(str, Enum):
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
