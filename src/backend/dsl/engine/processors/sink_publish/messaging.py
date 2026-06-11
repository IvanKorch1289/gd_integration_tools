"""S57 W4 — messaging.py part of sink_publish decomp.

Classes: MqPublishProcessor, WsPublishProcessor, MqttPublishProcessor.

messaging processors (MQ, WebSocket, MQTT).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor, handle_processor_error


@dataclass(slots=True)
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
        except Exception as exc:
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
