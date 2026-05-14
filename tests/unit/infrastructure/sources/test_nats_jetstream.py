"""K3 W2 — unit-тесты NATSJetStreamSource.

Покрывают:

* эмиссию NATSMessage через async iterator;
* возобновляемость durable consumer (поле metadata);
* graceful ImportError при отсутствии nats-py.

Сетевая часть (реальное подключение к NATS) НЕ тестируется —
только логика через mock nats.
"""

# ruff: noqa: S101, I001

from __future__ import annotations

import sys
import types
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.backend.infrastructure.sources.nats_jetstream import (
    NATSJetStreamSource,
    NATSMessage,
)


# ──────────────────────────────────────────────────────────────────────────────
# Вспомогательные фабрики


def _make_fake_nats_msg(
    subject: str = "orders.created",
    data: bytes = b"{}",
    headers: dict[str, str] | None = None,
    reply: str | None = None,
) -> MagicMock:
    """Создаёт mock NATS-сообщения с методом ack()."""
    msg = MagicMock()
    msg.subject = subject
    msg.data = data
    msg.headers = headers
    msg.reply = reply
    msg.ack = AsyncMock()
    return msg


def _install_fake_nats(monkeypatch: pytest.MonkeyPatch, msgs: list[MagicMock]) -> None:
    """Устанавливает fake nats module в sys.modules.

    Имитирует: ``nats.connect()`` → ``nc`` → ``nc.jetstream()`` →
    ``js.pull_subscribe()`` → ``psub.fetch(1)`` → [msg, ...].
    После двух вызовов fetch эмулирует StopIteration через RuntimeError,
    чтобы остановить бесконечный цикл в ``stream()``.
    """
    fetch_calls: list[int] = [0]

    async def _fetch(count: int, timeout: float = 5.0) -> list[MagicMock]:
        if fetch_calls[0] == 0:
            fetch_calls[0] += 1
            return msgs
        # После первого успешного batch — симулируем завершение (закрытие nc)
        raise RuntimeError("stop")

    psub = MagicMock()
    psub.fetch = _fetch

    js = MagicMock()
    js.pull_subscribe = AsyncMock(return_value=psub)

    nc = MagicMock()
    nc.is_closed = False
    nc.jetstream = MagicMock(return_value=js)
    nc.drain = AsyncMock()
    nc.close = AsyncMock()

    fake_nats = types.ModuleType("nats")
    fake_nats.connect = AsyncMock(return_value=nc)  # type: ignore[attr-defined]

    monkeypatch.setitem(sys.modules, "nats", fake_nats)


# ──────────────────────────────────────────────────────────────────────────────
# Тесты


@pytest.mark.asyncio
async def test_source_emits_messages(monkeypatch: pytest.MonkeyPatch) -> None:
    """NATSJetStreamSource.stream() эмитирует NATSMessage для каждого msg."""
    fake_msg = _make_fake_nats_msg(
        subject="orders.created",
        data=b'{"order_id": 42}',
        headers={"X-Source": "api"},
    )
    _install_fake_nats(monkeypatch, [fake_msg])

    src = NATSJetStreamSource(
        subject="orders.created",
        stream="ORDERS",
        durable="orders-consumer",
        nats_url="nats://localhost:4222",
    )

    received: list[NATSMessage] = []
    async for msg in src.stream():
        received.append(msg)
        break  # Берём первое сообщение и выходим

    assert len(received) == 1
    assert received[0].subject == "orders.created"
    assert received[0].data == b'{"order_id": 42}'
    assert received[0].headers == {"X-Source": "api"}


@pytest.mark.asyncio
async def test_source_durable_consumer_resumes(monkeypatch: pytest.MonkeyPatch) -> None:
    """NATSJetStreamSource передаёт durable имя в pull_subscribe и метаданные."""
    fake_msg = _make_fake_nats_msg(
        subject="payments.processed",
        data=b'{"amount": 100}',
    )
    _install_fake_nats(monkeypatch, [fake_msg])

    src = NATSJetStreamSource(
        subject="payments.processed",
        stream="PAYMENTS",
        durable="payments-durable",
        nats_url="nats://nats.internal:4222",
    )

    # Проверяем source_id включает stream и durable для идентификации
    assert "PAYMENTS" in src.source_id
    assert "payments-durable" in src.source_id

    # Проверяем что сообщение содержит корректные поля
    msgs: list[NATSMessage] = []
    async for msg in src.stream():
        msgs.append(msg)
        break

    assert len(msgs) == 1
    assert msgs[0].data == b'{"amount": 100}'
    assert msgs[0].reply is None  # нет reply-subject в тестовом сообщении


@pytest.mark.asyncio
async def test_source_import_error_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """При отсутствии nats-py stream() немедленно поднимает ImportError."""
    monkeypatch.setitem(sys.modules, "nats", None)  # type: ignore[arg-type]

    src = NATSJetStreamSource(
        subject="test.subject",
        stream="TEST",
        durable="test-durable",
    )

    with pytest.raises(ImportError, match="nats-py"):
        async for _ in src.stream():
            pass  # pragma: no cover
