"""W23 — Контракт исходящего канала (симметрия для Source).

``Sink`` — единый интерфейс для отправки нагрузки во внешнюю систему:
HTTP/SOAP/gRPC/MQ/Mail/SMS. Конкретные бэкенды живут в
``infrastructure/sinks/<kind>/`` и регистрируются в ``SinkRegistry``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol, runtime_checkable

__all__ = ("SinkKind", "SinkResult", "Sink")


class SinkKind(str, Enum):
    """Тип исходящего канала."""

    HTTP = "http"
    SOAP = "soap"
    GRPC = "grpc"
    MQ = "mq"
    MAIL = "mail"
    SMS = "sms"


@dataclass(slots=True)
class SinkResult:
    """Результат отправки во внешний канал.

    Args:
        ok: Успех отправки (HTTP 2xx / publish-ack / SMTP-OK).
        external_id: Идентификатор сообщения у получателя (если есть).
        details: backend-специфичные поля (status_code, queue_offset, ...).
    """

    ok: bool
    external_id: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class Sink(Protocol):
    """Универсальный контракт исходящего канала (W23 Gateway).

    Реализации:

    * ``infrastructure.sinks.http.HttpSink`` — REST.
    * ``infrastructure.sinks.mq.MQSink`` — Kafka/Rabbit/NATS/Redis.
    * ``infrastructure.sinks.mail.MailSink`` — SMTP.
    * ... и др. по ``SinkKind``.
    """

    sink_id: str
    kind: SinkKind

    async def send(self, payload: Any) -> SinkResult:
        """Отправить ``payload`` в целевой канал.

        Args:
            payload: Полезная нагрузка (dict/bytes/str — backend знает).

        Returns:
            ``SinkResult`` с флагом успеха и метаданными доставки.
        """
        ...

    async def health(self) -> bool:
        """Быстрая проверка работоспособности (для health-aggregator)."""
        ...
