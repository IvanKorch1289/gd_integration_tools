"""S107 W5 — unit-тесты NatsSource (real runtime).

Покрывают:

* эмиссию NatsMessage через async iterator (mock nats.connect + subscribe);
* reconnect-loop при ошибке подключения (max_reconnect_attempts exhaustion);
* graceful ImportError при отсутствии nats-py;
* start() callback-обёртку (Source-контракт);
* stop() и health() liveness-проверки;
* валидацию аргументов конструктора.

Сетевая часть (реальное подключение к NATS) НЕ тестируется —
только логика через mock nats-py.
"""

# ruff: noqa: S101, I001

from __future__ import annotations

import asyncio
import sys
import types
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.backend.infrastructure.sources.nats import NatsMessage, NatsSource


# ──────────────────────────────────────────────────────────────────────────────
# Вспомогательные фабрики


def _make_fake_nats_msg(
    subject: str = "orders.created",
    data: bytes = b"{}",
    reply: str | None = None,
) -> MagicMock:
    """Создаёт mock NATS-сообщения."""
    msg = MagicMock()
    msg.subject = subject
    msg.data = data
    msg.reply = reply
    return msg


def _install_fake_nats(
    monkeypatch: pytest.MonkeyPatch,
    msgs: list[MagicMock],
    *,
    connect_raises: Exception | None = None,
    connect_call_count: list[int] | None = None,
) -> None:
    """Устанавливает fake nats module в sys.modules.

    Имитирует: ``nats.connect()`` → ``nc`` → ``nc.subscribe()`` →
    ``sub.next_msg()`` → [msg, ...]. После исчерпания ``msgs``
    ``next_msg`` бросает ``RuntimeError("stop")`` — имитация
    cursor closed. Если ``connect_raises`` задан, ``nats.connect``
    бросает его.
    """
    if connect_call_count is None:
        connect_call_count = [0]

    msg_iter = iter(msgs)

    async def _next_msg(timeout: float = 5.0) -> MagicMock:
        try:
            return next(msg_iter)
        except StopIteration:
            raise RuntimeError("stop")

    sub = MagicMock()
    sub.next_msg = _next_msg
    sub.unsubscribe = AsyncMock()

    nc = MagicMock()
    nc.is_closed = False
    nc.drain = AsyncMock()
    nc.close = AsyncMock()
    nc.subscribe = AsyncMock(return_value=sub)

    async def _connect(url: str):
        connect_call_count[0] += 1
        if connect_raises is not None:
            raise connect_raises
        return nc

    fake_nats = types.ModuleType("nats")
    fake_nats.connect = _connect  # type: ignore[attr-defined]

    monkeypatch.setitem(sys.modules, "nats", fake_nats)


# ──────────────────────────────────────────────────────────────────────────────
# Тесты


def test_construction_validates_subject() -> None:
    """Пустой subject → ValueError."""
    with pytest.raises(ValueError, match="subject обязателен"):
        NatsSource(subject="")
    NatsSource(subject="orders.created")  # smoke: не падает


def test_construction_validates_reconnect_params() -> None:
    """max_reconnect_attempts < 0 → ValueError, delay < 0 → ValueError."""
    with pytest.raises(ValueError, match="max_reconnect_attempts"):
        NatsSource(subject="x", max_reconnect_attempts=-1)
    with pytest.raises(ValueError, match="reconnect_delay_seconds"):
        NatsSource(subject="x", reconnect_delay_seconds=-0.5)


def test_source_id_format() -> None:
    """source_id включает prefix 'nats:' + subject."""
    src = NatsSource(subject="orders.created", nats_url="nats://localhost:4222")
    assert src.source_id == "nats:orders.created"


def test_kind_is_mq() -> None:
    """SourceKind.MQ для NATS core."""
    src = NatsSource(subject="x")
    assert src.kind.value == "mq"


@pytest.mark.asyncio
async def test_stream_emits_messages(monkeypatch: pytest.MonkeyPatch) -> None:
    """NatsSource.stream() эмитирует NatsMessage для каждого входящего msg."""
    fake_msg = _make_fake_nats_msg(
        subject="orders.created", data=b'{"order_id": 42}', reply="orders.reply"
    )
    _install_fake_nats(monkeypatch, [fake_msg])

    src = NatsSource(subject="orders.created", nats_url="nats://localhost:4222")

    received: list[NatsMessage] = []
    async for msg in src.stream():
        received.append(msg)
        break  # Берём первое сообщение и выходим

    assert len(received) == 1
    assert received[0].subject == "orders.created"
    assert received[0].data == b'{"order_id": 42}'
    assert received[0].reply == "orders.reply"
    assert isinstance(received[0].timestamp, datetime)


@pytest.mark.asyncio
async def test_stream_raises_when_already_running(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Если _running=True (предыдущий stream не остановлен) → RuntimeError."""
    _install_fake_nats(monkeypatch, [])

    src = NatsSource(subject="test.subject")
    # Симулируем активную подписку
    src._running = True

    with pytest.raises(RuntimeError, match="уже запущен"):
        async for _ in src.stream():
            pass  # pragma: no cover


@pytest.mark.asyncio
async def test_stream_import_error_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """При отсутствии nats-py stream() немедленно поднимает ImportError."""
    # Удаляем nats из sys.modules (или подсовываем None)
    monkeypatch.delitem(sys.modules, "nats", raising=False)

    # Делаем import nats невозможным
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "nats":
            raise ImportError("No module named 'nats'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    src = NatsSource(subject="test.subject")

    with pytest.raises(ImportError, match="nats-py not installed"):
        async for _ in src.stream():
            pass  # pragma: no cover


@pytest.mark.asyncio
async def test_stream_reconnect_exhausted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """При постоянной ошибке connect — RuntimeError после max_attempts."""
    _install_fake_nats(
        monkeypatch,
        [],
        connect_raises=ConnectionError("nats unreachable"),
    )

    src = NatsSource(
        subject="x",
        nats_url="nats://localhost:4222",
        max_reconnect_attempts=2,
        reconnect_delay_seconds=0.01,
    )

    with pytest.raises(RuntimeError, match="max reconnect attempts"):
        async for _ in src.stream():
            pass  # pragma: no cover


@pytest.mark.asyncio
async def test_stream_reconnects_after_initial_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Первый connect fails, второй succeeds → сообщение эмитируется."""
    connect_calls: list[int] = [0]

    async def _connect(url: str):
        connect_calls[0] += 1
        if connect_calls[0] == 1:
            raise ConnectionError("transient")

        # Второй call: success
        sub = MagicMock()
        sub.next_msg = AsyncMock(
            side_effect=[
                _make_fake_nats_msg(subject="x", data=b"first"),
                RuntimeError("stop"),
            ]
        )
        sub.unsubscribe = AsyncMock()
        nc = MagicMock()
        nc.is_closed = False
        nc.drain = AsyncMock()
        nc.close = AsyncMock()
        nc.subscribe = AsyncMock(return_value=sub)
        return nc

    fake_nats = types.ModuleType("nats")
    fake_nats.connect = _connect  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "nats", fake_nats)

    src = NatsSource(
        subject="x",
        max_reconnect_attempts=3,
        reconnect_delay_seconds=0.01,
    )

    received: list[NatsMessage] = []
    async for msg in src.stream():
        received.append(msg)
        break

    assert connect_calls[0] == 2
    assert len(received) == 1
    assert received[0].data == b"first"


@pytest.mark.asyncio
async def test_start_invokes_callback(monkeypatch: pytest.MonkeyPatch) -> None:
    """start() оборачивает stream() и эмитит SourceEvent через callback."""
    fake_msg = _make_fake_nats_msg(subject="x", data=b'{"k": 1}')
    _install_fake_nats(monkeypatch, [fake_msg])

    src = NatsSource(subject="x")

    received_events: list = []

    async def on_event(ev):
        received_events.append(ev)
        # Останавливаем stream после первого события
        src._running = False

    on_event_mock = AsyncMock(side_effect=on_event)

    # Запускаем start() и ждём первый callback
    task = asyncio.create_task(src.start(on_event_mock))
    for _ in range(50):
        await asyncio.sleep(0.01)
        if received_events:
            break

    try:
        await asyncio.wait_for(task, timeout=2.0)
    except (asyncio.TimeoutError, asyncio.CancelledError):
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass

    assert len(received_events) >= 1
    assert received_events[0].source_id == "nats:x"
    assert received_events[0].kind.value == "mq"
    assert received_events[0].payload == b'{"k": 1}'


@pytest.mark.asyncio
async def test_start_callback_error_does_not_stop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ошибка в on_event не прерывает итерацию (логируется)."""
    fake_msg = _make_fake_nats_msg(subject="x", data=b"{}")
    _install_fake_nats(monkeypatch, [fake_msg])

    src = NatsSource(subject="x")
    call_count = [0]

    async def on_event_boom(ev):
        call_count[0] += 1
        src._running = False  # остановим после первого
        raise ValueError("callback boom")

    on_event = AsyncMock(side_effect=on_event_boom)

    task = asyncio.create_task(src.start(on_event))
    for _ in range(50):
        await asyncio.sleep(0.01)
        if call_count[0] >= 1:
            break

    try:
        await asyncio.wait_for(task, timeout=2.0)
    except (asyncio.TimeoutError, asyncio.CancelledError):
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass

    # Проверяем: on_event был вызван хотя бы раз (и упал)
    assert on_event.call_count >= 1


@pytest.mark.asyncio
async def test_stop_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    """stop() можно вызывать многократно без ошибок."""
    _install_fake_nats(monkeypatch, [])

    src = NatsSource(subject="x")
    await src.stop()
    await src.stop()  # double-stop без падения
    assert src._running is False
    assert src._nc is None


@pytest.mark.asyncio
async def test_health_initially_false() -> None:
    """health() == False до запуска stream()."""
    src = NatsSource(subject="x")
    assert await src.health() is False


@pytest.mark.asyncio
async def test_natsmessage_timestamp_default() -> None:
    """NatsMessage.timestamp default — datetime.now(UTC)."""
    msg = NatsMessage(subject="x", data=b"")
    assert isinstance(msg.timestamp, datetime)


@pytest.mark.asyncio
async def test_natsmessage_reply_optional() -> None:
    """NatsMessage.reply = None по дефолту."""
    msg = NatsMessage(subject="x", data=b"")
    assert msg.reply is None
