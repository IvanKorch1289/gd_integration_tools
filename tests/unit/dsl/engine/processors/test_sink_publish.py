# ruff: noqa: S101
"""Unit-тесты для sink_publish процессоров.

Покрывает GrpcCallProcessor, SoapCallProcessor, MqPublishProcessor,
WsPublishProcessor, MqttPublishProcessor, GenericSinkPublishProcessor.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.dsl.engine.processors.sink_publish import (
    GenericSinkPublishProcessor,
    GrpcCallProcessor,
    MqPublishProcessor,
    MqttPublishProcessor,
    SoapCallProcessor,
    WsPublishProcessor,
    _resolve_payload,
    _store_result,
)


@dataclass
class _FakeSinkResult:
    ok: bool
    details: dict[str, Any]


class _Message:
    def __init__(self, body: Any = None, headers: dict[str, str] | None = None) -> None:
        self.body = body
        self.headers = headers or {}

    def set_body(self, value: Any) -> None:
        self.body = value


class _Exchange:
    def __init__(self, body: Any = None) -> None:
        self.in_message = _Message(body=body)
        self.properties: dict[str, Any] = {}
        self._out_message: _Message | None = None

    def set_property(self, key: str, value: Any) -> None:
        self.properties[key] = value

    def set_out(self, *, body: Any, headers: dict[str, str]) -> None:
        self._out_message = _Message(body=body, headers=headers)


class _Context:
    pass


class TestResolvePayload:
    """``_resolve_payload`` — извлечение payload."""

    def test_from_property(self) -> None:
        ex = _Exchange()
        ex.properties["p"] = {"data": 1}
        assert _resolve_payload(ex, "p") == {"data": 1}

    def test_fallback_to_body(self) -> None:
        ex = _Exchange(body="hello")
        assert _resolve_payload(ex, None) == "hello"

    def test_missing_property_falls_back(self) -> None:
        ex = _Exchange(body="fallback")
        assert _resolve_payload(ex, "missing") == "fallback"


class TestStoreResult:
    """_store_result — сохранение результата."""

    def test_sets_property_and_out(self) -> None:
        ex = _Exchange()
        spec = MagicMock()
        spec.result_property = "res"
        spec.set_out = True
        _store_result(ex, spec, {"ok": True})
        assert ex.properties["res"] == {"ok": True}
        assert ex._out_message is not None
        assert ex._out_message.body == {"ok": True}

    def test_property_only_when_set_out_false(self) -> None:
        ex = _Exchange()
        spec = MagicMock()
        spec.result_property = "res"
        spec.set_out = False
        _store_result(ex, spec, {"ok": True})
        assert ex.properties["res"] == {"ok": True}
        assert ex._out_message is None


@pytest.mark.asyncio
class TestGrpcCallProcessor:
    """GrpcCallProcessor."""

    async def test_success(self) -> None:
        proc = GrpcCallProcessor(target="localhost:50051", full_method="/svc/m")
        exchange = _Exchange(body={"key": "val"})

        mock_sink = AsyncMock()
        mock_sink.send.return_value = _FakeSinkResult(
            ok=True, details={"method": "/svc/m"}
        )

        with patch(
            "src.backend.infrastructure.sinks.grpc_sink.GrpcSink",
            return_value=mock_sink,
        ):
            await proc.process(exchange, _Context())

        assert exchange.properties["grpc_result"]["ok"] is True
        mock_sink.send.assert_awaited_once_with({"key": "val"})

    async def test_payload_property(self) -> None:
        proc = GrpcCallProcessor(
            target="t", full_method="m", payload_property="payload"
        )
        exchange = _Exchange()
        exchange.properties["payload"] = [1, 2]

        mock_sink = AsyncMock()
        mock_sink.send.return_value = _FakeSinkResult(ok=True, details={})

        with patch(
            "src.backend.infrastructure.sinks.grpc_sink.GrpcSink",
            return_value=mock_sink,
        ):
            await proc.process(exchange, _Context())

        mock_sink.send.assert_awaited_once_with([1, 2])

    def test_to_spec(self) -> None:
        proc = GrpcCallProcessor(
            target="t",
            full_method="m",
            secure=False,
            timeout=5.0,
            payload_property="p",
            result_property="res",
        )
        assert proc.to_spec() == {
            "grpc_call": {
                "target": "t",
                "full_method": "m",
                "secure": False,
                "timeout": 5.0,
                "result_property": "res",
                "payload_property": "p",
            }
        }


@pytest.mark.asyncio
class TestSoapCallProcessor:
    """SoapCallProcessor."""

    async def test_success(self) -> None:
        proc = SoapCallProcessor(wsdl_url="http://wsdl", operation="op")
        exchange = _Exchange(body={"a": 1})

        mock_sink = AsyncMock()
        mock_sink.send.return_value = _FakeSinkResult(ok=True, details={"resp": "ok"})

        with patch(
            "src.backend.infrastructure.sinks.soap_sink.SoapSink",
            return_value=mock_sink,
        ):
            await proc.process(exchange, _Context())

        assert exchange.properties["soap_result"]["ok"] is True
        assert exchange.properties["soap_result"]["resp"] == "ok"

    def test_to_spec(self) -> None:
        proc = SoapCallProcessor(
            wsdl_url="w", operation="o", service_name="s", port_name="p", timeout=10.0
        )
        spec = proc.to_spec()["soap_call"]
        assert spec["service_name"] == "s"
        assert spec["port_name"] == "p"


@pytest.mark.asyncio
class TestMqPublishProcessor:
    """MqPublishProcessor."""

    async def test_success(self) -> None:
        proc = MqPublishProcessor(broker="kafka", url="k://localhost", topic="t")
        exchange = _Exchange(body={"msg": "hi"})

        mock_sink = AsyncMock()
        mock_sink.send.return_value = _FakeSinkResult(ok=True, details={})

        with patch(
            "src.backend.infrastructure.sinks.mq_sink.MqSink", return_value=mock_sink
        ):
            await proc.process(exchange, _Context())

        assert exchange.properties["mq_publish_result"]["ok"] is True

    def test_to_spec_with_extra(self) -> None:
        proc = MqPublishProcessor(
            broker="rabbit", url="amqp://localhost", topic="q", extra={"durable": True}
        )
        spec = proc.to_spec()["mq_publish"]
        assert spec["extra"] == {"durable": True}


@pytest.mark.asyncio
class TestWsPublishProcessor:
    """WsPublishProcessor."""

    async def test_success(self) -> None:
        proc = WsPublishProcessor(url="ws://localhost")
        exchange = _Exchange(body="hello")

        mock_sink = AsyncMock()
        mock_sink.send.return_value = _FakeSinkResult(ok=True, details={})

        with patch(
            "src.backend.infrastructure.sinks.ws_sink.WsSink", return_value=mock_sink
        ):
            await proc.process(exchange, _Context())

        assert exchange.properties["ws_publish_result"]["ok"] is True

    def test_to_spec_with_headers(self) -> None:
        proc = WsPublishProcessor(
            url="ws://localhost",
            extra_headers={"X-Auth": "token"},
            payload_property="p",
        )
        spec = proc.to_spec()["ws_publish"]
        assert spec["extra_headers"] == {"X-Auth": "token"}
        assert spec["payload_property"] == "p"


@pytest.mark.asyncio
class TestMqttPublishProcessor:
    """MqttPublishProcessor."""

    async def test_success(self) -> None:
        proc = MqttPublishProcessor(host="broker", topic="t")
        exchange = _Exchange(body={"temp": 22})

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("aiomqtt.Client", return_value=mock_client):
            await proc.process(exchange, _Context())

        assert exchange.properties["mqtt_publish_result"]["ok"] is True
        mock_client.publish.assert_awaited_once()

    async def test_import_error_stores_failure(self) -> None:
        import sys
        from builtins import __import__ as real_import

        proc = MqttPublishProcessor(host="broker", topic="t")
        exchange = _Exchange(body="hi")

        def _fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
            if name == "aiomqtt":
                raise ImportError("no aiomqtt")
            return real_import(name, *args, **kwargs)

        with (
            patch.dict(sys.modules, {"aiomqtt": None}),
            patch("builtins.__import__", _fake_import),
        ):
            await proc.process(exchange, _Context())

        assert exchange.properties["mqtt_publish_result"]["ok"] is False
        assert "aiomqtt" in exchange.properties["mqtt_publish_result"]["error"]

    async def test_publish_error_stores_failure(self) -> None:
        proc = MqttPublishProcessor(host="broker", topic="t")
        exchange = _Exchange(body="hi")

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.publish.side_effect = RuntimeError("conn lost")

        with patch("aiomqtt.Client", return_value=mock_client):
            await proc.process(exchange, _Context())

        assert exchange.properties["mqtt_publish_result"]["ok"] is False
        assert "conn lost" in exchange.properties["mqtt_publish_result"]["error"]

    async def test_string_payload_sent_directly(self) -> None:
        proc = MqttPublishProcessor(host="broker", topic="t")
        exchange = _Exchange(body="raw")

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("aiomqtt.Client", return_value=mock_client):
            await proc.process(exchange, _Context())

        call_args = mock_client.publish.call_args
        assert call_args[1]["payload"] == "raw"

    def test_init_reads_default_port(self) -> None:
        # S164 W40: MqttSettings moved to core.config.services.mqtt (not
        # entrypoints.mqtt.mqtt_handler). Verify wiring with real default.
        proc = MqttPublishProcessor(host="h", topic="t")
        # Default port is 1883 (standard MQTT) per core.config.services.mqtt
        assert proc._port == 1883

    def test_to_spec(self) -> None:
        proc = MqttPublishProcessor(
            host="h",
            topic="t",
            port=1883,
            qos=1,
            retain=True,
            username="u",
            password="p",
        )
        spec = proc.to_spec()["mqtt_publish"]
        assert spec["qos"] == 1
        assert spec["retain"] is True
        assert spec["username"] == "u"
        assert spec["password"] == "p"


@pytest.mark.asyncio
class TestGenericSinkPublishProcessor:
    """GenericSinkPublishProcessor."""

    async def test_success(self) -> None:
        proc = GenericSinkPublishProcessor(
            kind="http", config={"url": "http://example.com"}
        )
        exchange = _Exchange(body={"data": 1})

        mock_sink = AsyncMock()
        mock_sink.send.return_value = _FakeSinkResult(ok=True, details={"status": 200})

        with patch(
            "src.backend.infrastructure.sinks.factory.build_sink",
            return_value=mock_sink,
        ):
            await proc.process(exchange, _Context())

        assert exchange.properties["sink_publish_result"]["ok"] is True
        assert exchange.properties["sink_publish_result"]["status"] == 200

    async def test_build_sink_error_stores_failure(self) -> None:
        proc = GenericSinkPublishProcessor(kind="http", config={})
        exchange = _Exchange()

        with patch(
            "src.backend.infrastructure.sinks.factory.build_sink",
            side_effect=ValueError("bad config"),
        ):
            await proc.process(exchange, _Context())

        assert exchange.properties["sink_publish_result"]["ok"] is False
        assert "bad config" in exchange.properties["sink_publish_result"]["error"]

    def test_invalid_kind_raises(self) -> None:
        with pytest.raises(ValueError, match="kind must be one of"):
            GenericSinkPublishProcessor(kind="unknown", config={})

    def test_to_spec(self) -> None:
        proc = GenericSinkPublishProcessor(
            kind="s3",
            config={"bucket": "b"},
            payload_property="p",
            result_property="res",
        )
        assert proc.to_spec() == {
            "sink_publish": {
                "kind": "s3",
                "config": {"bucket": "b"},
                "result_property": "res",
                "payload_property": "p",
            }
        }
