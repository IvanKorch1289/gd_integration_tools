"""Sprint 3 — unit-тесты MqttSink (V16.1 P1)."""

# ruff: noqa: S101

from __future__ import annotations

import sys
import types
from typing import Any

import pytest

from src.backend.core.interfaces.sink import SinkKind
from src.backend.infrastructure.sinks.factory import build_sink
from src.backend.infrastructure.sinks.mqtt_sink import MqttSink


class _FakeMqttClient:
    """Имитатор aiomqtt.Client без сетевых вызовов."""

    last_publish: tuple[str, Any, int, bool] | None = None

    def __init__(self, **_: Any) -> None:
        type(self).last_publish = None

    async def __aenter__(self) -> _FakeMqttClient:
        return self

    async def __aexit__(self, *_: Any) -> None:
        return None

    async def publish(
        self, topic: str, payload: Any, qos: int = 0, retain: bool = False
    ) -> None:
        type(self).last_publish = (topic, payload, qos, retain)


@pytest.fixture
def fake_aiomqtt(monkeypatch: pytest.MonkeyPatch) -> types.ModuleType:
    """Подменяет ``aiomqtt`` на in-memory stub."""
    fake_module = types.ModuleType("aiomqtt")
    fake_module.Client = _FakeMqttClient  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "aiomqtt", fake_module)
    return fake_module


@pytest.mark.asyncio
async def test_kind_is_mqtt() -> None:
    sink = MqttSink(sink_id="m1", broker_host="h", topic="t/x")
    assert sink.kind == SinkKind.MQTT


@pytest.mark.asyncio
async def test_send_dict_serializes_via_orjson(fake_aiomqtt: types.ModuleType) -> None:
    sink = MqttSink(
        sink_id="m1",
        broker_host="broker.local",
        broker_port=1883,
        topic="gd/orders/created",
        qos=1,
    )
    result = await sink.send({"order_id": 42})
    assert result.ok is True
    assert result.details["topic"] == "gd/orders/created"
    assert result.details["qos"] == 1
    topic, payload, qos, retain = _FakeMqttClient.last_publish  # type: ignore[misc]
    assert topic == "gd/orders/created"
    assert isinstance(payload, bytes)
    assert payload == b'{"order_id":42}'
    assert qos == 1
    assert retain is False


@pytest.mark.asyncio
async def test_send_bytes_passthrough(fake_aiomqtt: types.ModuleType) -> None:
    sink = MqttSink(
        sink_id="m2", broker_host="broker.local", topic="gd/raw", retain=True
    )
    await sink.send(b"raw-bytes")
    _, payload, _, retain = _FakeMqttClient.last_publish  # type: ignore[misc]
    assert payload == b"raw-bytes"
    assert retain is True


@pytest.mark.asyncio
async def test_send_str_passthrough(fake_aiomqtt: types.ModuleType) -> None:
    sink = MqttSink(sink_id="m3", broker_host="h", topic="t/x")
    await sink.send("hello-text")
    _, payload, _, _ = _FakeMqttClient.last_publish  # type: ignore[misc]
    assert payload == "hello-text"


@pytest.mark.asyncio
async def test_send_returns_ok_false_when_aiomqtt_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "aiomqtt", None)  # type: ignore[arg-type]
    sink = MqttSink(sink_id="m4", broker_host="h", topic="t/x")
    result = await sink.send({"k": 1})
    assert result.ok is False
    assert "aiomqtt" in result.details["error"]


@pytest.mark.asyncio
async def test_send_handles_publish_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_module = types.ModuleType("aiomqtt")

    class _BoomClient:
        def __init__(self, **_: Any) -> None: ...
        async def __aenter__(self) -> _BoomClient:
            return self

        async def __aexit__(self, *_: Any) -> None:
            return None

        async def publish(self, *_: Any, **__: Any) -> None:
            raise RuntimeError("publish failed")

    fake_module.Client = _BoomClient  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "aiomqtt", fake_module)

    sink = MqttSink(sink_id="m5", broker_host="h", topic="t/x")
    result = await sink.send({"k": 1})
    assert result.ok is False
    assert result.details["error"] == "publish failed"


@pytest.mark.asyncio
async def test_health_returns_true_when_connect_ok(
    fake_aiomqtt: types.ModuleType,
) -> None:
    sink = MqttSink(sink_id="m6", broker_host="h", topic="t/x")
    assert await sink.health() is True


@pytest.mark.asyncio
async def test_health_returns_false_when_aiomqtt_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "aiomqtt", None)  # type: ignore[arg-type]
    sink = MqttSink(sink_id="m7", broker_host="h", topic="t/x")
    assert await sink.health() is False


def test_factory_builds_mqtt_sink() -> None:
    sink = build_sink(
        {
            "sink_id": "alerts.mqtt",
            "kind": "mqtt",
            "broker_host": "broker.local",
            "broker_port": 1883,
            "topic": "gd/alerts",
            "qos": 1,
        }
    )
    assert isinstance(sink, MqttSink)
    assert sink.sink_id == "alerts.mqtt"
    assert sink.kind == SinkKind.MQTT
    assert sink.topic == "gd/alerts"


def test_tls_context_disabled_when_flag_false() -> None:
    sink = MqttSink(sink_id="m8", broker_host="h", topic="t", tls_enabled=False)
    assert sink._build_tls_context() is None


def test_tls_context_enabled_when_flag_true() -> None:
    sink = MqttSink(sink_id="m9", broker_host="h", topic="t", tls_enabled=True)
    ctx = sink._build_tls_context()
    assert ctx is not None
    assert ctx.check_hostname is True


@pytest.mark.asyncio
async def test_health_returns_false_on_connect_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_module = types.ModuleType("aiomqtt")

    class _BoomClient:
        def __init__(self, **_: Any) -> None: ...
        async def __aenter__(self) -> Any:
            raise ConnectionRefusedError("nope")

        async def __aexit__(self, *_: Any) -> None:
            return None

    fake_module.Client = _BoomClient  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "aiomqtt", fake_module)
    sink = MqttSink(sink_id="m10", broker_host="h", topic="t/x")
    assert await sink.health() is False


def test_tls_context_mtls() -> None:
    sink = MqttSink(
        sink_id="m11",
        broker_host="h",
        topic="t",
        tls_enabled=True,
        client_cert_path="/tmp/cert.pem",
        client_key_path="/tmp/key.pem",
    )
    # load_cert_chain will raise because files don't exist; that's fine for this unit test
    with pytest.raises(FileNotFoundError):
        sink._build_tls_context()
