"""Wave 3.2 — DSL-процессоры исходящих протоколов (Sink-symmetric).

Все процессоры используют :class:`~src.core.interfaces.sink.Sink`
напрямую — sink конструируется из параметров процессора (один sink
per call, без записи в ``SinkRegistry``). Альтернативный режим
``sink_id=...`` берёт уже зарегистрированный sink через
``services.sources.registry.get_sink_registry()`` (Wave 3.3).

Покрываемые kind-ы:

* :class:`GrpcCallProcessor` — ``.sink_grpc(target=..., ...)`` / ``.grpc_call(...)``
* :class:`SoapCallProcessor` — ``.sink_soap(target=..., ...)`` / ``.soap_call(...)``
* :class:`MqPublishProcessor` — ``.sink_mq(...)`` / ``.mq_publish(...)``
* :class:`WsPublishProcessor` — ``.sink_ws(target=URL, ...)`` / ``.ws_publish(...)``
* :class:`MqttPublishProcessor` — ``.sink_mqtt(...)`` / ``.mqtt_publish(...)``
* :class:`GenericSinkPublishProcessor` — обобщённый sink_publish для
  ``email`` / ``webhook`` / ``file`` / ``http`` / ``s3`` (Sprint 3 W1 K3).

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
from src.backend.dsl.registry import processor

__all__ = (
    "GenericSinkPublishProcessor",
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


@processor(
    "grpc_call",
    namespace="core",
    spec_schema={
        "type": "object",
        "properties": {
            "target": {"type": "string"},
            "full_method": {"type": "string"},
            "secure": {"type": "boolean"},
            "timeout": {"type": "number"},
            "payload_property": {"type": ["string", "null"]},
            "result_property": {"type": "string"},
        },
        "required": ["target", "full_method"],
    },
    meta={"tier": 2, "category": "sink"},
)
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

    def to_spec(self) -> dict[str, Any]:
        """YAML round-trip spec."""
        spec: dict[str, Any] = {
            "target": self._target,
            "full_method": self._full_method,
            "secure": self._secure,
            "timeout": self._timeout,
            "result_property": self._out.result_property,
        }
        if self._payload_property is not None:
            spec["payload_property"] = self._payload_property
        return {"grpc_call": spec}


@processor(
    "soap_call",
    namespace="core",
    spec_schema={
        "type": "object",
        "properties": {
            "wsdl_url": {"type": "string"},
            "operation": {"type": "string"},
            "service_name": {"type": ["string", "null"]},
            "port_name": {"type": ["string", "null"]},
            "timeout": {"type": "number"},
            "payload_property": {"type": ["string", "null"]},
            "result_property": {"type": "string"},
        },
        "required": ["wsdl_url", "operation"],
    },
    meta={"tier": 2, "category": "sink"},
)
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

    def to_spec(self) -> dict[str, Any]:
        """YAML round-trip spec."""
        spec: dict[str, Any] = {
            "wsdl_url": self._wsdl_url,
            "operation": self._operation,
            "timeout": self._timeout,
            "result_property": self._out.result_property,
        }
        if self._service_name is not None:
            spec["service_name"] = self._service_name
        if self._port_name is not None:
            spec["port_name"] = self._port_name
        if self._payload_property is not None:
            spec["payload_property"] = self._payload_property
        return {"soap_call": spec}


@processor(
    "mq_publish",
    namespace="core",
    spec_schema={
        "type": "object",
        "properties": {
            "broker": {"type": "string", "enum": ["kafka", "rabbit", "redis", "nats"]},
            "url": {"type": "string"},
            "topic": {"type": "string"},
            "extra": {"type": "object"},
            "payload_property": {"type": ["string", "null"]},
            "result_property": {"type": "string"},
        },
        "required": ["broker", "url", "topic"],
    },
    meta={"tier": 2, "category": "sink"},
)
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

    def to_spec(self) -> dict[str, Any]:
        """YAML round-trip spec."""
        spec: dict[str, Any] = {
            "broker": self._broker,
            "url": self._url,
            "topic": self._topic,
            "result_property": self._out.result_property,
        }
        if self._extra:
            spec["extra"] = dict(self._extra)
        if self._payload_property is not None:
            spec["payload_property"] = self._payload_property
        return {"mq_publish": spec}


@processor(
    "ws_publish",
    namespace="core",
    spec_schema={
        "type": "object",
        "properties": {
            "url": {"type": "string"},
            "extra_headers": {"type": "object"},
            "timeout": {"type": "number"},
            "payload_property": {"type": ["string", "null"]},
            "result_property": {"type": "string"},
        },
        "required": ["url"],
    },
    meta={"tier": 2, "category": "sink"},
)
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

    def to_spec(self) -> dict[str, Any]:
        """YAML round-trip spec."""
        spec: dict[str, Any] = {
            "url": self._url,
            "timeout": self._timeout,
            "result_property": self._out.result_property,
        }
        if self._extra_headers:
            spec["extra_headers"] = dict(self._extra_headers)
        if self._payload_property is not None:
            spec["payload_property"] = self._payload_property
        return {"ws_publish": spec}


@processor(
    "mqtt_publish",
    namespace="core",
    spec_schema={
        "type": "object",
        "properties": {
            "host": {"type": "string"},
            "topic": {"type": "string"},
            "port": {"type": "integer"},
            "qos": {"type": "integer", "enum": [0, 1, 2]},
            "retain": {"type": "boolean"},
            "username": {"type": ["string", "null"]},
            "password": {"type": ["string", "null"]},
            "payload_property": {"type": ["string", "null"]},
            "result_property": {"type": "string"},
        },
        "required": ["host", "topic"],
    },
    meta={"tier": 2, "category": "sink"},
)
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
        port: int | None = None,
        qos: int = 0,
        retain: bool = False,
        username: str | None = None,
        password: str | None = None,
        payload_property: str | None = None,
        result_property: str = "mqtt_publish_result",
        name: str | None = None,
    ) -> None:
        """Сохраняет MQTT broker config; клиент создаётся при ``process``."""
        from src.backend.entrypoints.mqtt.mqtt_handler import MqttSettings

        if port is None:
            port = MqttSettings().broker_port
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

    def to_spec(self) -> dict[str, Any]:
        """YAML round-trip spec."""
        spec: dict[str, Any] = {
            "host": self._host,
            "topic": self._topic,
            "port": self._port,
            "qos": self._qos,
            "retain": self._retain,
            "result_property": self._out.result_property,
        }
        if self._username is not None:
            spec["username"] = self._username
        if self._password is not None:
            spec["password"] = self._password
        if self._payload_property is not None:
            spec["payload_property"] = self._payload_property
        return {"mqtt_publish": spec}


# ── Обобщённый sink_publish для email / webhook / file / http / s3 ──


_GENERIC_SINK_KINDS = frozenset({"http", "webhook", "file", "email", "s3"})


@processor(
    "sink_publish",
    namespace="core",
    spec_schema={
        "type": "object",
        "properties": {
            "kind": {"type": "string", "enum": sorted(_GENERIC_SINK_KINDS)},
            "config": {"type": "object"},
            "payload_property": {"type": ["string", "null"]},
            "result_property": {"type": "string"},
        },
        "required": ["kind", "config"],
    },
    meta={"tier": 2, "category": "sink"},
)
class GenericSinkPublishProcessor(BaseProcessor):
    """``.sink_publish(kind=..., config={...})`` — обобщённый sink publisher.

    Использует :func:`~src.backend.infrastructure.sinks.factory.build_sink`
    для построения Sink-экземпляра из declarative-spec и публикует
    payload через ``Sink.send(payload)``. Симметрия с Sink-классами
    в :mod:`infrastructure.sinks` без дублирования специализированных
    PublishProcessor-ов для gRPC/SOAP/MQ/WS/MQTT.

    Args:
        kind: Один из ``"http"`` / ``"webhook"`` / ``"file"`` /
            ``"email"`` / ``"s3"`` (новые Sink-методы Sprint 3 W1 K3).
        config: Конкретные параметры Sink-класса (без ``sink_id`` и
            ``kind`` — они выставляются автоматически).
        payload_property: Откуда брать payload (None → ``in_message.body``).
        result_property: Куда писать результат публикации.
    """

    def __init__(
        self,
        *,
        kind: str,
        config: dict[str, Any],
        payload_property: str | None = None,
        result_property: str = "sink_publish_result",
        name: str | None = None,
    ) -> None:
        if kind not in _GENERIC_SINK_KINDS:
            allowed = ", ".join(sorted(_GENERIC_SINK_KINDS))
            raise ValueError(
                f"sink_publish: kind must be one of {allowed}, got {kind!r}"
            )
        super().__init__(name=name or f"sink_publish:{kind}")
        self._kind = kind
        self._config = dict(config)
        self._payload_property = payload_property
        self._out = _OutSpec(result_property=result_property)

    @handle_processor_error
    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Конструирует Sink через factory и публикует ``payload``."""
        from src.backend.infrastructure.sinks.factory import build_sink

        spec: dict[str, Any] = {
            "sink_id": self.name or f"sink_publish:{self._kind}",
            "kind": self._kind,
            **self._config,
        }
        try:
            sink = build_sink(spec)
        except ValueError as exc:
            _store_result(exchange, self._out, {"ok": False, "error": str(exc)})
            return

        payload = _resolve_payload(exchange, self._payload_property)
        result = await sink.send(payload)
        _store_result(exchange, self._out, {"ok": result.ok, **result.details})

    def to_spec(self) -> dict[str, Any]:
        """YAML round-trip spec."""
        spec: dict[str, Any] = {
            "kind": self._kind,
            "config": dict(self._config),
            "result_property": self._out.result_property,
        }
        if self._payload_property is not None:
            spec["payload_property"] = self._payload_property
        return {"sink_publish": spec}
