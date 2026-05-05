# ruff: noqa: S101
"""Тесты `NotifyCascadeProcessor` (R2.3)."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from src.core.interfaces.notification import NotificationAdapter, NotificationMessage
from src.dsl.engine.context import ExecutionContext
from src.dsl.engine.exchange import Exchange, Message
from src.dsl.engine.processors.notify_cascade import NotifyCascadeProcessor


class _FakeAdapter(NotificationAdapter):
    """Канал-имитация для тестов."""

    def __init__(
        self,
        channel: str,
        *,
        available: bool = True,
        fail_send: type[Exception] | None = None,
        succeed_after: int = 0,
    ) -> None:
        self.channel = channel
        self._available = available
        self._fail_send = fail_send
        self._succeed_after = succeed_after
        self.send_calls = 0
        self.sent: list[NotificationMessage] = []

    async def send(self, message: NotificationMessage) -> str:
        self.send_calls += 1
        if self._fail_send is not None and self.send_calls <= self._succeed_after:
            raise self._fail_send(f"{self.channel}: fail #{self.send_calls}")
        self.sent.append(message)
        return f"{self.channel}-track-{self.send_calls}"

    async def is_available(self) -> bool:
        return self._available


def _make_exchange(
    body: Any = None, properties: dict[str, Any] | None = None
) -> Exchange[Any]:
    ex = Exchange(in_message=Message(body=body))
    if properties:
        ex.properties.update(properties)
    return ex


async def _wait_tasks(exchange: Exchange[Any]) -> None:
    """Ждём завершения всех background tasks из notify_cascade_tasks."""
    # Простая стратегия: gather всех _all_tasks через event loop.
    # У нас 1 task на process() — сделаем sleep до завершения через poll.
    for _ in range(50):
        await asyncio.sleep(0.02)
        if all(
            t.done() for t in asyncio.all_tasks() if t is not asyncio.current_task()
        ):
            return


@pytest.mark.asyncio
class TestNotifyCascadeBasic:
    async def test_sends_via_first_available(self) -> None:
        a = _FakeAdapter("slack")
        b = _FakeAdapter("email")
        proc = NotifyCascadeProcessor(
            adapters=[a, b],
            recipient_path="properties.recipient",
            subject="Hello",
            body_path="body",
        )
        ex = _make_exchange(body="msg", properties={"recipient": "user@bank.io"})
        await proc.process(ex, ExecutionContext())
        await _wait_tasks(ex)

        assert a.send_calls == 1
        assert a.sent[0].recipient == "user@bank.io"
        assert a.sent[0].subject == "Hello"
        assert a.sent[0].body == "msg"
        assert b.send_calls == 0  # fallback не активирован

    async def test_falls_back_when_first_unavailable(self) -> None:
        a = _FakeAdapter("slack", available=False)
        b = _FakeAdapter("email")
        proc = NotifyCascadeProcessor(
            adapters=[a, b], recipient_path="properties.recipient"
        )
        ex = _make_exchange(properties={"recipient": "u@b.io"})
        await proc.process(ex, ExecutionContext())
        await _wait_tasks(ex)

        assert a.send_calls == 0  # не пробуем — is_available=False
        assert b.send_calls == 1

    async def test_falls_back_on_connection_error(self) -> None:
        a = _FakeAdapter("slack", fail_send=ConnectionError, succeed_after=10)
        b = _FakeAdapter("email")
        proc = NotifyCascadeProcessor(
            adapters=[a, b],
            recipient_path="properties.recipient",
            retries_per_adapter=2,
            retry_delay_s=0.001,
        )
        ex = _make_exchange(properties={"recipient": "u@b.io"})
        await proc.process(ex, ExecutionContext())
        await _wait_tasks(ex)

        assert a.send_calls == 2  # 2 retry на slack
        assert b.send_calls == 1  # потом email — успех

    async def test_retry_succeeds_within_same_adapter(self) -> None:
        a = _FakeAdapter("slack", fail_send=ConnectionError, succeed_after=1)
        b = _FakeAdapter("email")
        proc = NotifyCascadeProcessor(
            adapters=[a, b],
            recipient_path="properties.recipient",
            retries_per_adapter=3,
            retry_delay_s=0.001,
        )
        ex = _make_exchange(properties={"recipient": "u@b.io"})
        await proc.process(ex, ExecutionContext())
        await _wait_tasks(ex)

        assert a.send_calls == 2  # 1 fail + 1 success
        assert b.send_calls == 0  # fallback не активирован

    async def test_non_connection_error_skips_to_next_adapter(self) -> None:
        # ValueError — не ConnectionError, retry не применяется,
        # сразу fallback на следующий.
        a = _FakeAdapter("slack", fail_send=ValueError, succeed_after=10)
        b = _FakeAdapter("email")
        proc = NotifyCascadeProcessor(
            adapters=[a, b],
            recipient_path="properties.recipient",
            retries_per_adapter=5,
            retry_delay_s=0.001,
        )
        ex = _make_exchange(properties={"recipient": "u@b.io"})
        await proc.process(ex, ExecutionContext())
        await _wait_tasks(ex)

        assert a.send_calls == 1  # один раз — без retry на ValueError
        assert b.send_calls == 1


@pytest.mark.asyncio
class TestNotifyCascadeNonBlocking:
    async def test_process_returns_immediately(self) -> None:
        # Adapter держит send() длинным — process() всё равно
        # должен вернуться без блока.
        a = _SlowAdapter(delay=1.0)
        proc = NotifyCascadeProcessor(
            adapters=[a], recipient_path="properties.recipient"
        )
        ex = _make_exchange(properties={"recipient": "u@b.io"})

        loop = asyncio.get_running_loop()
        t0 = loop.time()
        await proc.process(ex, ExecutionContext())
        elapsed = loop.time() - t0
        assert elapsed < 0.1  # process() не дождался send'а

        # Cleanup: cancel slow task.
        for t in asyncio.all_tasks():
            if t.get_name().startswith("notify_cascade"):
                t.cancel()


class _SlowAdapter(NotificationAdapter):
    """Adapter с долгим send для проверки non-blocking."""

    channel = "slow"

    def __init__(self, *, delay: float) -> None:
        self._delay = delay

    async def send(self, message: NotificationMessage) -> str:
        await asyncio.sleep(self._delay)
        return "slow-track"

    async def is_available(self) -> bool:
        return True


class TestValidation:
    def test_empty_adapters_raises(self) -> None:
        with pytest.raises(ValueError, match="adapters list cannot be empty"):
            NotifyCascadeProcessor(adapters=[])


@pytest.mark.asyncio
class TestPathExtraction:
    async def test_body_path_dict(self) -> None:
        a = _FakeAdapter("slack")
        proc = NotifyCascadeProcessor(
            adapters=[a], recipient_path="body.user", body_path="body.text"
        )
        ex = _make_exchange(body={"user": "u@b.io", "text": "hello"})
        await proc.process(ex, ExecutionContext())
        await _wait_tasks(ex)
        assert a.sent[0].recipient == "u@b.io"
        assert a.sent[0].body == "hello"

    async def test_unsupported_path_raises(self) -> None:
        a = _FakeAdapter("slack")
        proc = NotifyCascadeProcessor(adapters=[a], recipient_path="bogus_path")
        ex = _make_exchange(body={"x": 1})
        with pytest.raises(ValueError, match="unsupported path"):
            await proc.process(ex, ExecutionContext())
