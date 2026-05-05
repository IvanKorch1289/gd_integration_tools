"""Wave 3 — реализации :class:`~src.core.interfaces.sink.Sink` (Roadmap V10).

Симметрия Source (9 типов) ↔ Sink (9 типов):

* :class:`~src.infrastructure.sinks.http_sink.HttpSink` — REST POST/PUT через httpx.
* :class:`~src.infrastructure.sinks.grpc_sink.GrpcSink` — unary RPC.
* :class:`~src.infrastructure.sinks.soap_sink.SoapSink` — SOAP/WSDL через zeep
  с обёрткой ``asyncio.to_thread`` (zeep — sync-only).
* :class:`~src.infrastructure.sinks.mq_sink.MqSink` — Kafka/Rabbit/Redis-Streams
  через FastStream-publisher.
* :class:`~src.infrastructure.sinks.ws_sink.WsSink` — outbound WebSocket
  publish (отдельный от inbound ``/ws``-handler канал).
* :class:`~src.infrastructure.sinks.webhook_sink.WebhookSink` — POST на URL с
  опциональным HMAC-подписанием.
* :class:`~src.infrastructure.sinks.file_sink.FileSink` — append/write на local FS.
* :class:`~src.infrastructure.sinks.email_sink.EmailSink` — SMTP через aiosmtplib.
* SMS — заглушка ``SmsSink`` (опционально, по требованию).

Тяжёлые backend-зависимости (``grpcio``, ``zeep``, ``faststream``, ``aiosmtplib``)
импортируются лениво в ``send()``/``health()`` — модуль ``infrastructure.sinks``
поднимается без них (graceful: без бэкенда метод вернёт
``SinkResult(ok=False, details={"error": "<lib> not installed"})``).
"""

from __future__ import annotations

from src.backend.infrastructure.sinks.email_sink import EmailSink
from src.backend.infrastructure.sinks.file_sink import FileSink
from src.backend.infrastructure.sinks.grpc_sink import GrpcSink
from src.backend.infrastructure.sinks.http_sink import HttpSink
from src.backend.infrastructure.sinks.mq_sink import MqSink
from src.backend.infrastructure.sinks.soap_sink import SoapSink
from src.backend.infrastructure.sinks.webhook_sink import WebhookSink
from src.backend.infrastructure.sinks.ws_sink import WsSink

__all__ = (
    "EmailSink",
    "FileSink",
    "GrpcSink",
    "HttpSink",
    "MqSink",
    "SoapSink",
    "WebhookSink",
    "WsSink",
)
