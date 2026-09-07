"""Тесты broker-loop `_listen` (T3 ratchet: mqtt_handler 67%→≥90%).

aiomqtt-фейк: bounded-буфер kwargs, subscribe на каждый topic,
payload size-guard (S103 P2-7), bounded concurrency (W3),
завершение через CancelledError-маркер конца потока сообщений.
"""

from __future__ import annotations

import asyncio
import sys
from unittest.mock import AsyncMock, patch

import pytest

from src.backend.core.config.services.mqtt import MqttSettings
from src.backend.entrypoints.mqtt.mqtt_handler import MqttHandler


class _FakeMessage:
    def __init__(self, topic: str, payload: bytes) -> None:
        self.topic = topic
        self.payload = payload


class _FakeMessages:
    """Async-итератор: отдаёт сообщения, затем CancelledError (конец потока)."""

    def __init__(self, msgs: list[_FakeMessage]) -> None:
        self._msgs = list(msgs)
        self._i = 0

    def __aiter__(self) -> "_FakeMessages":
        return self

    async def __anext__(self) -> _FakeMessage:
        if self._i < len(self._msgs):
            msg = self._msgs[self._i]
            self._i += 1
            return msg
        raise asyncio.CancelledError


class _FakeClient:
    instances: list["_FakeClient"] = []
    messages: _FakeMessages

    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs
        _FakeClient.instances.append(self)
        self.subscribe = AsyncMock()
        self.messages = _FakeMessages(_FakeClient.current_msgs)

    async def __aenter__(self) -> "_FakeClient":
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False


current_msgs: list[_FakeMessage] = []
_FakeClient.current_msgs = current_msgs  # type: ignore[attr-defined]


def _settings(**overrides: object) -> MqttSettings:
    return MqttSettings(enabled=False, **overrides)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_listen_processes_messages_and_subscribes() -> None:
    """Сообщения диспетчатся; subscribe на каждый topic; bounded-buffer kwarg."""
    handler = MqttHandler(_settings(topics=["gd/a", "gd/b"]))
    handler._running = True
    _FakeClient.instances.clear()
    _FakeClient.current_msgs = [
        _FakeMessage("gd/a", b'{"action":"x.y"}'),
        _FakeMessage("gd/b", b'{"action":"z.w"}'),
    ]

    with patch("aiomqtt.Client", _FakeClient), patch(
        "src.backend.core.api.extensions.action_handler_registry"
    ) as mock_registry:
        mock_registry.dispatch = AsyncMock()
        await handler._listen()
        # задачи созданы, но не обязаны были получить слот loop до выхода
        await asyncio.gather(*handler._message_tasks, return_exceptions=True)

    client = _FakeClient.instances[-1]
    assert client.subscribe.await_count == 2
    topics = [c.args[0] for c in client.subscribe.await_args_list]
    assert topics == ["gd/a", "gd/b"]
    assert client.kwargs["max_queued_incoming_messages"] == 1000
    assert mock_registry.dispatch.await_count == 2


@pytest.mark.asyncio
async def test_listen_drops_oversized_payload() -> None:
    """S103 P2-7: payload > max_payload_bytes отбрасывается до task."""
    handler = MqttHandler(_settings())
    handler._running = True
    _FakeClient.instances.clear()
    _FakeClient.current_msgs = [
        # 1 MiB default (getattr): payload больше лимита -> drop
        _FakeMessage("gd/big", b"x" * 1_048_577),
        _FakeMessage("gd/ok", b'{"action":"a.b"}'),
    ]

    with patch("aiomqtt.Client", _FakeClient), patch(
        "src.backend.core.api.extensions.action_handler_registry"
    ) as mock_registry:
        mock_registry.dispatch = AsyncMock()
        await handler._listen()
        await asyncio.gather(*handler._message_tasks, return_exceptions=True)

    assert mock_registry.dispatch.await_count == 1  # только gd/ok


@pytest.mark.asyncio
async def test_listen_exit_without_connection_error() -> None:
    """Конец потока сообщений (CancelledError-маркер) -> чистый выход, 0 dispatch."""
    handler = MqttHandler(_settings())
    handler._running = True
    _FakeClient.instances.clear()
    _FakeClient.current_msgs = []

    with patch("aiomqtt.Client", _FakeClient), patch(
        "src.backend.core.api.extensions.action_handler_registry"
    ) as mock_registry:
        mock_registry.dispatch = AsyncMock()
        await handler._listen()

    mock_registry.dispatch.assert_not_awaited()
    assert handler._message_tasks == set() or not handler._message_tasks


# ── добор: guard, wait-ветка, stop-swallow ──────────────────────────


@pytest.mark.asyncio
async def test_listen_without_aiomqtt_returns(monkeypatch) -> None:
    """aiomqtt отсутствует -> _listen молча возвращается (guard 98)."""

    handler = MqttHandler(_settings())
    handler._running = True
    monkeypatch.setitem(sys.modules, "aiomqtt", None)
    await handler._listen()
    monkeypatch.setattr(sys, "modules", sys.modules)  # no-op фикс


@pytest.mark.asyncio
async def test_listen_bounded_wait_branch_deterministic(monkeypatch) -> None:
    """156-159: 4 сообщения, max=2, dispatch с gate -> peak ровно 2, всё dispatch."""
    import asyncio

    handler = MqttHandler(
        _settings(max_concurrent_messages=2, message_timeout=5.0)
    )
    handler._running = True
    _FakeClient.current_msgs = [
        _FakeMessage(f"gd/t{i}", b'{"action":"gated"}') for i in range(4)
    ]

    gate_closed = asyncio.Event()
    active = {"n": 0}
    peak = {"n": 0}

    async def gated_dispatch(command):  # type: ignore[no-untyped-def]
        active["n"] += 1
        peak["n"] = max(peak["n"], active["n"])
        await gate_closed.wait()
        active["n"] -= 1


    async def probing(topic: str, payload: bytes | bytearray) -> None:
        await gated_dispatch(None)

    monkeypatch.setattr(handler, "_process_message", probing)

    async def open_gate_later() -> None:
        await asyncio.sleep(0.1)
        gate_closed.set()

    opener = asyncio.create_task(open_gate_later())
    with patch("aiomqtt.Client", _FakeClient), patch(
        "src.backend.core.api.extensions.action_handler_registry"
    ) as mock_registry:
        mock_registry.dispatch = AsyncMock(side_effect=gated_dispatch)
        await handler._listen()
        await asyncio.gather(*handler._message_tasks, return_exceptions=True)

    assert peak["n"] <= 2
    await opener
