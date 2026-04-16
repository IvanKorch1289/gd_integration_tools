"""Типы и конфигурации протоколов интеграционной шины.

Определяет перечисление всех поддерживаемых протоколов
и конфигурацию транспорта для DSL-маршрутов.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

__all__ = (
    "ProtocolType",
    "TransportConfig",
)


class ProtocolType(str, Enum):
    """Поддерживаемые протоколы интеграционной шины.

    Каждый протокол соответствует адаптеру в ``src/dsl/adapters/``,
    который преобразует входящие данные протокола в ``Exchange``
    и отправляет результат обратно.
    """

    rest = "rest"
    soap = "soap"
    grpc = "grpc"
    websocket = "websocket"
    graphql = "graphql"
    kafka = "kafka"
    redis_stream = "redis_stream"
    rabbitmq = "rabbitmq"
    webhook = "webhook"
    sse = "sse"
    email_imap = "email_imap"
    sftp = "sftp"
    ftp = "ftp"


@dataclass(slots=True)
class TransportConfig:
    """Конфигурация транспорта для DSL-маршрута.

    Определяет параметры подключения и поведения
    для конкретного протокола.

    Attrs:
        endpoint: Адрес подключения (URL, host:port и т.д.).
        timeout: Таймаут операции в секундах.
        retry_count: Количество повторных попыток.
        options: Протокол-специфичные параметры
            (например, ``group_id`` для Kafka,
            ``wsdl`` для SOAP).
    """

    endpoint: str | None = None
    timeout: float | None = None
    retry_count: int | None = None
    options: dict[str, Any] = field(default_factory=dict)
