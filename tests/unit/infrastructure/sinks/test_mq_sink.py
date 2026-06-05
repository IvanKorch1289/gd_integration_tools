"""Unit-tests for MqSink."""

# ruff: noqa: S101

from __future__ import annotations

import sys
import types
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.backend.core.interfaces.sink import SinkKind
from src.backend.infrastructure.sinks.mq_sink import MqSink


def _install_fake_broker(
    monkeypatch: pytest.MonkeyPatch,
    broker_name: str,
    raise_on_publish: Exception | None = None,
) -> MagicMock:
    """Install a fake faststream broker module."""
    fake_broker = MagicMock()
    fake_broker.connect = AsyncMock()
    fake_broker.close = AsyncMock()
    fake_broker.publish = AsyncMock(side_effect=raise_on_publish)

    fake_mod = types.ModuleType(f"faststream.{broker_name}")
    broker_cls = MagicMock(return_value=fake_broker)
    fake_mod.__dict__[f"{broker_name.capitalize()}Broker"] = broker_cls
    monkeypatch.setitem(sys.modules, f"faststream.{broker_name}", fake_mod)
    return fake_broker


@pytest.mark.asyncio
async def test_kind_is_mq() -> None:
    sink = MqSink(sink_id="q1", broker="kafka", url="k", topic="t")
    assert sink.kind == SinkKind.MQ


@pytest.mark.asyncio
async def test_send_kafka_success(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_broker = _install_fake_broker(monkeypatch, "kafka")
    sink = MqSink(sink_id="q1", broker="kafka", url="localhost:9092", topic="events")
    result = await sink.send({"evt": 1})
    assert result.ok is True
    assert result.details["broker"] == "kafka"
    assert result.details["topic"] == "events"
    fake_broker.connect.assert_awaited_once()
    fake_broker.publish.assert_awaited_once()
    fake_broker.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_send_rabbit_success(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_broker = _install_fake_broker(monkeypatch, "rabbit")
    sink = MqSink(
        sink_id="q2", broker="rabbit", url="amqp://guest@localhost", topic="q"
    )
    result = await sink.send("hello")
    assert result.ok is True
    fake_broker.publish.assert_awaited_once()


@pytest.mark.asyncio
async def test_send_redis_success(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_broker = _install_fake_broker(monkeypatch, "redis")
    sink = MqSink(sink_id="q3", broker="redis", url="redis://localhost", topic="s")
    result = await sink.send(b"raw")
    assert result.ok is True
    call_args = fake_broker.publish.call_args
    assert call_args[0][0] == b"raw"


@pytest.mark.asyncio
async def test_send_nats_success(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_broker(monkeypatch, "nats")
    sink = MqSink(sink_id="q4", broker="nats", url="nats://localhost", topic="subj")
    result = await sink.send({"x": 1})
    assert result.ok is True


@pytest.mark.asyncio
async def test_send_returns_false_when_broker_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "faststream.kafka", None)  # type: ignore[arg-type]
    sink = MqSink(sink_id="q5", broker="kafka", url="k", topic="t")
    result = await sink.send({})
    assert result.ok is False
    assert "faststream" in result.details["error"]


@pytest.mark.asyncio
async def test_send_handles_publish_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_broker(
        monkeypatch, "kafka", raise_on_publish=RuntimeError("broker down")
    )
    sink = MqSink(sink_id="q6", broker="kafka", url="k", topic="t")
    result = await sink.send({})
    assert result.ok is False
    assert "broker down" in result.details["error"]


@pytest.mark.asyncio
async def test_health_true(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_broker = _install_fake_broker(monkeypatch, "rabbit")
    sink = MqSink(sink_id="q7", broker="rabbit", url="amqp://x", topic="t")
    assert await sink.health() is True
    fake_broker.connect.assert_awaited_once()
    fake_broker.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_health_false_when_broker_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "faststream.kafka", None)  # type: ignore[arg-type]
    sink = MqSink(sink_id="q8", broker="kafka", url="k", topic="t")
    assert await sink.health() is False


@pytest.mark.asyncio
async def test_health_false_on_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_broker = _install_fake_broker(monkeypatch, "redis")
    fake_broker.connect = AsyncMock(side_effect=OSError("fail"))
    sink = MqSink(sink_id="q9", broker="redis", url="r", topic="t")
    assert await sink.health() is False
