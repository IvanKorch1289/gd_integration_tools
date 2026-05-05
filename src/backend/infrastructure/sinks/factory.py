"""Wave 3.3 — фабрика Sink из декларативной spec (YAML/dict).

Симметрична :mod:`services.sources.factory` (build_source). Принимает
spec вида ``{"sink_id": "...", "kind": "http", ...}`` и возвращает
:class:`~src.core.interfaces.sink.Sink`-экземпляр нужного класса.

Регистрация в :class:`~src.services.sources.registry.SinkRegistry`
производится отдельно composition-root'ом (``register_app_state`` →
``build_sink`` → ``sink_registry.register``).
"""

from __future__ import annotations

from typing import Any, Mapping

from src.backend.core.interfaces.sink import Sink, SinkKind
from src.backend.infrastructure.sinks.email_sink import EmailSink
from src.backend.infrastructure.sinks.file_sink import FileSink
from src.backend.infrastructure.sinks.grpc_sink import GrpcSink
from src.backend.infrastructure.sinks.http_sink import HttpSink
from src.backend.infrastructure.sinks.mq_sink import MqSink
from src.backend.infrastructure.sinks.soap_sink import SoapSink
from src.backend.infrastructure.sinks.webhook_sink import WebhookSink
from src.backend.infrastructure.sinks.ws_sink import WsSink

__all__ = ("build_sink",)


def build_sink(spec: Mapping[str, Any]) -> Sink:
    """Конструирует :class:`Sink` из declarative spec.

    Args:
        spec: Описание sink'а:
            ``{"sink_id": "alerts.http", "kind": "http",
            "url": "...", ...}``.

    Returns:
        Экземпляр конкретного Sink-класса.

    Raises:
        ValueError: Если ``kind`` неизвестен или ``sink_id`` отсутствует.
    """
    sink_id = spec.get("sink_id")
    if not sink_id:
        raise ValueError("sink_id is required")

    raw_kind = spec.get("kind")
    if not raw_kind:
        raise ValueError(f"sink {sink_id!r}: kind is required")

    kind = SinkKind(raw_kind) if not isinstance(raw_kind, SinkKind) else raw_kind
    common: dict[str, Any] = {
        k: v for k, v in spec.items() if k not in {"sink_id", "kind"}
    }

    match kind:
        case SinkKind.HTTP:
            return HttpSink(sink_id=sink_id, **common)
        case SinkKind.WEBHOOK:
            return WebhookSink(sink_id=sink_id, **common)
        case SinkKind.FILE:
            return FileSink(sink_id=sink_id, **common)
        case SinkKind.MAIL:
            return EmailSink(sink_id=sink_id, **common)
        case SinkKind.WS:
            return WsSink(sink_id=sink_id, **common)
        case SinkKind.GRPC:
            return GrpcSink(sink_id=sink_id, **common)
        case SinkKind.SOAP:
            return SoapSink(sink_id=sink_id, **common)
        case SinkKind.MQ:
            return MqSink(sink_id=sink_id, **common)
        case SinkKind.SMS:
            raise ValueError(
                f"sink {sink_id!r}: kind=sms — реализация отложена (Wave 9.x)"
            )
        case _:  # pragma: no cover — match покрывает все варианты enum.
            raise ValueError(f"sink {sink_id!r}: неизвестный kind={kind!r}")
