"""Wave 3.2 — DSL-процессоры исходящих протоколов (Sink-symmetric).

Все процессоры используют :class:`~src.core.interfaces.sink.Sink`
напрямую — sink конструируется из параметров процессора (один sink
per call, без записи в ``SinkRegistry``). Альтернативный режим
``sink_id=...`` берёт уже зарегистрированный sink через
``services.sources.registry.get_sink_registry()`` (Wave 3.3).

Покрываемые kind-ы:

* :class:`GrpcCallProcessor` — ``.grpc_call(target, method, ...)``
* :class:`SoapCallProcessor` — ``.soap_call(wsdl, operation, ...)``
* :class:`MqPublishProcessor` — ``.mq_publish(broker, url, topic, ...)``
* :class:`WsPublishProcessor` — ``.ws_publish(url, ...)``
* :class:`MqttPublishProcessor` — ``.mqtt_publish(host, port, topic, ...)``

Webhook/HTTP/File/Email уже покрыты другими процессорами
(``http_call``, ``file_export``, ``notify``) — Sink-классы доступны
для прямого использования composition root + DSL не дублирует их.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor, handle_processor_error

__all__ = (
    "GrpcCallProcessor",
    "MqPublishProcessor",
    "MqttPublishProcessor",
    "SoapCallProcessor",
    "WsPublishProcessor",
)


@dataclass(slots=True)
class _OutSpec:
    """Конфигурация сохранения результата в exchange (общая для всех Sink-процессоров).

    Attributes:
        result_property: Имя property в ``exchange.properties``.
        set_out: Записать результат также в ``exchange.out_message`` (default).
    """

    result_property: str
    set_out: bool = True


def _resolve_payload(exchange: Exchange[Any], payload_property: str | None) -> Any:
    """Извлекает payload из exchange (по property или из in_message.body)."""
    if payload_property:
        return exchange.properties.get(payload_property, exchange.in_message.body)
    return exchange.in_message.body


def _store_result(exchange: Exchange[Any], spec: _OutSpec, result: Any) -> None:
    """Сохраняет result в property и опционально в out_message."""
    exchange.set_property(spec.result_property, result)
    if spec.set_out:
        exchange.set_out(body=result, headers=dict(exchange.in_message.headers))


class GrpcCallProcessor(BaseProcessor):
    """``.grpc_call(target, method, ...)`` — unary gRPC-вызов."""

    def __init__(
        self,
        target: str,
        full_method: str,
        *,
        secure: bool = True,
        timeout: float = 10.0,
        payload_property: str | None = None,
        result_property: str = "grpc_result",
        name: str | None = None,
    ) -> None:
        """Сохраняет параметры sink — реальный экземпляр строится при ``process``."""
        super().__init__(name=name or f"grpc_call:{full_method}")
        self._target = target
        self._full_method = full_method
        self._secure = secure
        self._timeout = timeout
        self._payload_property = payload_property
        self._out = _OutSpec(result_property=result_property)

    @handle_processor_error
    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Конструирует :class:`GrpcSink` и публикует ``payload``."""
        from src.backend.infrastructure.sinks.grpc_sink import GrpcSink

        sink = GrpcSink(
            sink_id=self.name or "grpc_call",
            target=self._target,
            full_method=self._full_method,
            secure=self._secure,
            timeout=self._timeout,
        )
        payload = _resolve_payload(exchange, self._payload_property)
        result = await sink.send(payload)
        _store_result(exchange, self._out, {"ok": result.ok, **result.details})


class SoapCallProcessor(BaseProcessor):
    """``.soap_call(wsdl, operation, ...)`` — SOAP/WSDL операция через zeep."""

    def __init__(
        self,
        wsdl_url: str,
        operation: str,
        *,
        service_name: str | None = None,
        port_name: str | None = None,
        timeout: float = 30.0,
        payload_property: str | None = None,
        result_property: str = "soap_result",
        name: str | None = None,
    ) -> None:
        """Сохраняет параметры; SOAP-клиент кэшируется внутри ``SoapSink``."""
        super().__init__(name=name or f"soap_call:{operation}")
        self._wsdl_url = wsdl_url
        self._operation = operation
        self._service_name = service_name
        self._port_name = port_name
        self._timeout = timeout
        self._payload_property = payload_property
        self._out = _OutSpec(result_property=result_property)

    @handle_processor_error
    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Конструирует :class:`SoapSink` и вызывает SOAP-операцию."""
        from src.backend.infrastructure.sinks.soap_sink import SoapSink

        sink = SoapSink(
            sink_id=self.name or "soap_call",
            wsdl_url=self._wsdl_url,
            operation=self._operation,
            service_name=self._service_name,
            port_name=self._port_name,
            timeout=self._timeout,
        )
        payload = _resolve_payload(exchange, self._payload_property)
        result = await sink.send(payload)
        _store_result(exchange, self._out, {"ok": result.ok, **result.details})


class MqPublishProcessor(BaseProcessor):
    """``.mq_publish(broker, url, topic)`` — публикация в Kafka/Rabbit/Redis/NATS."""

    def __init__(
        self,
        broker: str,
        url: str,
        topic: str,
        *,
        extra: dict[str, Any] | None = None,
        payload_property: str | None = None,
        result_property: str = "mq_publish_result",
        name: str | None = None,
    ) -> None:
        """Сохраняет broker-config; FastStream-broker строится при ``process``."""
        super().__init__(name=name or f"mq_publish:{broker}:{topic}")
        self._broker = broker
        self._url = url
        self._topic = topic
        self._extra = extra or {}
        self._payload_property = payload_property
        self._out = _OutSpec(result_property=result_property)

    @handle_processor_error
    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Конструирует :class:`MqSink` и публикует ``payload``."""
        from src.backend.infrastructure.sinks.mq_sink import MqSink

        sink = MqSink(
            sink_id=self.name or f"mq:{self._broker}",
            broker=self._broker,
            url=self._url,
            topic=self._topic,
            extra=dict(self._extra),
        )
        payload = _resolve_payload(exchange, self._payload_property)
        result = await sink.send(payload)
        _store_result(exchange, self._out, {"ok": result.ok, **result.details})


class WsPublishProcessor(BaseProcessor):
    """``.ws_publish(url)`` — outbound WebSocket publish (короткое соединение)."""

    def __init__(
        self,
        url: str,
        *,
        extra_headers: dict[str, str] | None = None,
        timeout: float = 10.0,
        payload_property: str | None = None,
        result_property: str = "ws_publish_result",
        name: str | None = None,
    ) -> None:
        """Сохраняет URL и заголовки handshake."""
        super().__init__(name=name or "ws_publish")
        self._url = url
        self._extra_headers = extra_headers or {}
        self._timeout = timeout
        self._payload_property = payload_property
        self._out = _OutSpec(result_property=result_property)

    @handle_processor_error
    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Конструирует :class:`WsSink` и публикует payload."""
        from src.backend.infrastructure.sinks.ws_sink import WsSink

        sink = WsSink(
            sink_id=self.name or "ws_publish",
            url=self._url,
            extra_headers=dict(self._extra_headers),
            timeout=self._timeout,
        )
        payload = _resolve_payload(exchange, self._payload_property)
        result = await sink.send(payload)
        _store_result(exchange, self._out, {"ok": result.ok, **result.details})


class MqttPublishProcessor(BaseProcessor):
    """``.mqtt_publish(host, port, topic, ...)`` — публикация в MQTT-брокер.

    Реализован поверх ``aiomqtt`` (lazy-импорт). Если ``aiomqtt`` не
    установлен — процессор пишет в exchange ошибку без падения, что
    согласовано с graceful-семантикой Sink'ов.
    """

    def __init__(
        self,
        host: str,
        topic: str,
        *,
        port: int = 1883,
        qos: int = 0,
        retain: bool = False,
        username: str | None = None,
        password: str | None = None,
        payload_property: str | None = None,
        result_property: str = "mqtt_publish_result",
        name: str | None = None,
    ) -> None:
        """Сохраняет MQTT broker config; клиент создаётся при ``process``."""
        super().__init__(name=name or f"mqtt_publish:{topic}")
        self._host = host
        self._port = port
        self._topic = topic
        self._qos = qos
        self._retain = retain
        self._username = username
        self._password = password
        self._payload_property = payload_property
        self._out = _OutSpec(result_property=result_property)

    @handle_processor_error
    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Открывает MQTT-соединение через aiomqtt и публикует payload."""
        try:
            import aiomqtt
        except ImportError:
            _store_result(
                exchange, self._out, {"ok": False, "error": "aiomqtt not installed"}
            )
            return

        payload = _resolve_payload(exchange, self._payload_property)
        body = (
            payload
            if isinstance(payload, (bytes, str))
            else json.dumps(payload, ensure_ascii=False, default=str)
        )

        try:
            async with aiomqtt.Client(
                hostname=self._host,
                port=self._port,
                username=self._username,
                password=self._password,
            ) as client:
                await client.publish(
                    self._topic, payload=body, qos=self._qos, retain=self._retain
                )
        except Exception as exc:  # noqa: BLE001
            _store_result(
                exchange,
                self._out,
                {"ok": False, "error": str(exc) or exc.__class__.__name__},
            )
            return

        _store_result(
            exchange, self._out, {"ok": True, "topic": self._topic, "qos": self._qos}
        )
