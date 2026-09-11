"""Focused tests for ``ReplyChannel`` (Sprint 24 coverage ratchet).

Цель: поднять покрытие ``src/backend/infrastructure/clients/messaging/reply_channel.py``
с ~21% до ≥70% путём детального покрытия request/deliver механизма без
Redis (используется in-process fallback когда ``event_bus._broker is None``).

Контракт API (см. reply_channel.py):
- ``__init__(event_bus)`` — pending dict + lock + subscribed flag.
- ``instance(event_bus=None)`` — singleton; первый вызов требует bus.
- ``request(*, target_channel, payload, timeout=30, correlation_id=None)``
  публикует запрос в target_channel и ждёт reply; raises ReplyTimeoutError.
- ``deliver(reply)`` — handler для reply-сообщений; True если доставлено.
- ``_ensure_subscribed()`` — lazy subscribe on broker; fallback in-process.
- ``_bus_publish_raw(channel, message)`` — publish dict (для raw payloads).
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any

import pytest

from src.backend.infrastructure.clients.messaging.event_bus import EventBus
from src.backend.infrastructure.clients.messaging.reply_channel import (
    DEFAULT_REPLY_TIMEOUT_S,
    REPLY_CHANNEL_PREFIX,
    ReplyChannel,
    ReplyTimeoutError,
)


@pytest.fixture
def event_bus_no_redis() -> EventBus:
    """EventBus без started broker → in-process fallback."""
    # Сбрасываем singleton перед каждым тестом.
    ReplyChannel._instance = None
    return EventBus()


@pytest.fixture
def reply_channel(event_bus_no_redis: EventBus) -> ReplyChannel:
    """ReplyChannel на in-process EventBus (без Redis)."""
    return ReplyChannel(event_bus_no_redis)


class TestReplyChannelInit:
    """``__init__`` + singleton bookkeeping."""

    def test_init_starts_empty(
        self, event_bus_no_redis: EventBus
    ) -> None:
        """``__init__`` создаёт пустые pending/lock/subscribed."""
        rc = ReplyChannel(event_bus_no_redis)
        assert rc._bus is event_bus_no_redis
        assert rc._pending == {}
        assert isinstance(rc._lock, asyncio.Lock)
        assert rc._subscribed is False

    def test_singleton_returns_same_instance(
        self, event_bus_no_redis: EventBus
    ) -> None:
        """``instance()`` возвращает один и тот же объект."""
        rc1 = ReplyChannel.instance(event_bus=event_bus_no_redis)
        rc2 = ReplyChannel.instance()
        assert rc1 is rc2


class TestReplyChannelRequest:
    """``request()`` — публикация + ожидание reply."""

    async def test_request_times_out_without_reply(
        self, reply_channel: ReplyChannel
    ) -> None:
        """``request()`` без deliver → ``ReplyTimeoutError`` после timeout."""
        # timeout=0.05s чтобы не тянуть 30s.
        with pytest.raises(ReplyTimeoutError) as exc_info:
            await reply_channel.request(
                target_channel="events.tests",
                payload={"q": "hello"},
                timeout=0.05,
            )
        # Сообщение содержит correlation_id и timeout.
        assert "0.05" in str(exc_info.value) or "timeout" in str(exc_info.value).lower()

    async def test_request_succeeds_after_deliver(
        self, reply_channel: ReplyChannel
    ) -> None:
        """``request()`` резолвится после matching ``deliver()``."""
        # Запускаем request в фоне с коротким timeout.
        async def _run_request() -> dict[str, Any]:
            return await reply_channel.request(
                target_channel="events.tests",
                payload={"q": "test"},
                timeout=2.0,
            )

        request_task = asyncio.create_task(_run_request())
        # Даём request'у время дойти до ``await asyncio.wait_for``.
        await asyncio.sleep(0.05)

        # Извлекаем correlation_id из pending.
        assert len(reply_channel._pending) == 1
        cid = next(iter(reply_channel._pending.keys()))

        # Доставляем reply.
        delivered = await reply_channel.deliver(
            {"correlation_id": cid, "payload": {"answer": 42}}
        )
        assert delivered is True

        result = await asyncio.wait_for(request_task, timeout=1.0)
        assert result == {"answer": 42}
        # После успеха pending очищен.
        assert cid not in reply_channel._pending

    async def test_request_uses_provided_correlation_id(
        self, reply_channel: ReplyChannel
    ) -> None:
        """``request(correlation_id=...)`` использует переданный ID."""
        cid = "test-correlation-123"

        async def _run_request() -> dict[str, Any]:
            return await reply_channel.request(
                target_channel="events.tests",
                payload={"x": 1},
                timeout=2.0,
                correlation_id=cid,
            )

        request_task = asyncio.create_task(_run_request())
        await asyncio.sleep(0.05)

        # pending содержит ровно наш cid.
        assert cid in reply_channel._pending

        await reply_channel.deliver(
            {"correlation_id": cid, "payload": {"ok": True}}
        )
        result = await asyncio.wait_for(request_task, timeout=1.0)
        assert result == {"ok": True}

    async def test_request_rejects_duplicate_correlation_id(
        self, reply_channel: ReplyChannel
    ) -> None:
        """Повторный request с тем же correlation_id → ValueError."""
        cid = "dup-cid"

        async def _first_request() -> None:
            with contextlib.suppress(ReplyTimeoutError):
                await reply_channel.request(
                    target_channel="events.tests",
                    payload={"first": True},
                    timeout=2.0,
                    correlation_id=cid,
                )

        first_task = asyncio.create_task(_first_request())
        await asyncio.sleep(0.05)
        assert cid in reply_channel._pending

        # Второй request с тем же cid — должно бросить ValueError.
        with pytest.raises(ValueError) as exc_info:
            await reply_channel.request(
                target_channel="events.tests",
                payload={"second": True},
                timeout=0.1,
                correlation_id=cid,
            )
        assert cid in str(exc_info.value)

        # Cleanup.
        await reply_channel.deliver(
            {"correlation_id": cid, "payload": {"cleanup": True}}
        )
        await first_task


class TestReplyChannelDeliver:
    """``deliver()`` — handler для reply-сообщений."""

    async def test_deliver_without_correlation_id_returns_false(
        self, reply_channel: ReplyChannel
    ) -> None:
        """``deliver()`` без correlation_id → False (no-op)."""
        result = await reply_channel.deliver({"payload": {"x": 1}})
        assert result is False

    async def test_deliver_unknown_correlation_id_returns_false(
        self, reply_channel: ReplyChannel
    ) -> None:
        """``deliver()`` с неизвестным cid → False (stale reply)."""
        result = await reply_channel.deliver(
            {"correlation_id": "unknown-cid", "payload": {"x": 1}}
        )
        assert result is False

    async def test_deliver_empty_correlation_id_returns_false(
        self, reply_channel: ReplyChannel
    ) -> None:
        """``deliver()`` с пустым cid → False."""
        result = await reply_channel.deliver({"correlation_id": "", "payload": {}})
        assert result is False


class TestReplyChannelSubscribe:
    """``_ensure_subscribed()`` — lazy broker subscription."""

    async def test_ensure_subscribed_with_no_broker(
        self, reply_channel: ReplyChannel
    ) -> None:
        """``_ensure_subscribed()`` без broker → in-process fallback, ``_subscribed=True``."""
        # event_bus_no_redis._broker is None
        assert reply_channel._subscribed is False
        await reply_channel._ensure_subscribed()
        assert reply_channel._subscribed is True

    async def test_ensure_subscribed_is_idempotent(
        self, reply_channel: ReplyChannel
    ) -> None:
        """``_ensure_subscribed()`` после первого вызова — no-op."""
        await reply_channel._ensure_subscribed()
        # Повторный вызов не должен ничего делать.
        await reply_channel._ensure_subscribed()
        assert reply_channel._subscribed is True


class TestReplyChannelPublishRaw:
    """``_bus_publish_raw()`` — fallback при отсутствии broker."""

    async def test_publish_raw_without_broker_no_op(
        self, reply_channel: ReplyChannel
    ) -> None:
        """``_bus_publish_raw()`` без broker → silent no-op (warning logged)."""
        # event_bus_no_redis._broker is None → должно просто вернуться.
        await reply_channel._bus_publish_raw(
            "events.tests", {"correlation_id": "x", "payload": {"q": 1}}
        )


class TestConstants:
    """Module-level constants."""

    def test_default_reply_timeout_is_30s(self) -> None:
        """``DEFAULT_REPLY_TIMEOUT_S == 30.0``."""
        assert DEFAULT_REPLY_TIMEOUT_S == 30.0

    def test_reply_channel_prefix(self) -> None:
        """``REPLY_CHANNEL_PREFIX == 'events.replies.'``."""
        assert REPLY_CHANNEL_PREFIX == "events.replies."


class TestReplyTimeoutError:
    """``ReplyTimeoutError`` — наследник ``asyncio.TimeoutError``."""

    def test_inherits_from_timeout_error(self) -> None:
        """``ReplyTimeoutError`` — подкласс ``asyncio.TimeoutError``."""
        assert issubclass(ReplyTimeoutError, asyncio.TimeoutError)

    def test_can_be_raised_and_caught(self) -> None:
        """``ReplyTimeoutError`` ловится как ``asyncio.TimeoutError``."""
        with pytest.raises(asyncio.TimeoutError):
            raise ReplyTimeoutError("test timeout")
