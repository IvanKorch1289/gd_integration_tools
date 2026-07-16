"""Unit-тесты для HitlPubSubConsumer (S178 HITL-1 closeout).

Используем AsyncMock для ``redis.pubsub()`` чтобы не зависеть от реального
Redis. Тестируем: psubscribe+listen loop, signal_id filter через callback,
graceful error handling, lifecycle start/stop.
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.services.workflows.hitl_pubsub import HITL_CHANNEL_PREFIX
from src.backend.services.workflows.hitl_pubsub_consumer import (
    HitlPubSubConsumer,
)


def _make_pubsub_mock() -> MagicMock:
    """Build mock pubsub с async-iterator по синтетическим messages."""
    pubsub = MagicMock()
    pubsub.psubscribe = AsyncMock()
    pubsub.close = AsyncMock()
    return pubsub


def _make_wrapper_mock(pubsub: MagicMock) -> MagicMock:
    """Build mock ``RedisClient.get_client`` wrapper."""
    wrapper = MagicMock()
    raw = MagicMock()
    raw.pubsub.return_value = pubsub
    wrapper.get_client = AsyncMock(return_value=raw)
    return wrapper


@pytest.mark.asyncio
async def test_start_returns_false_when_redis_unavailable() -> None:
    """Если Redis падает → start() возвращает False + log warning."""
    consumer = HitlPubSubConsumer()

    async def on_message(msg: dict) -> None:  # pragma: no cover - never called
        pass

    with patch(
        "src.backend.infrastructure.clients.storage.redis.get_redis_client",
        side_effect=RuntimeError("redis down"),
    ):
        result = await consumer.start(on_message=on_message)

    assert result is False
    assert consumer.started is False


@pytest.mark.asyncio
async def test_start_subscribes_wildcard_pattern() -> None:
    """Успешный start → psubscribe на wildcard ``hitl:resolved:*``."""
    pubsub = _make_pubsub_mock()
    wrapper = _make_wrapper_mock(pubsub)

    consumer = HitlPubSubConsumer()

    async def on_message(msg: dict) -> None:  # pragma: no cover - no messages
        pass

    with patch(
        "src.backend.infrastructure.clients.storage.redis.get_redis_client",
        return_value=wrapper,
    ):
        result = await consumer.start(on_message=on_message)

    assert result is True
    assert consumer.started is True
    expected_pattern = f"{HITL_CHANNEL_PREFIX}:*"
    pubsub.psubscribe.assert_awaited_once_with(expected_pattern)
    await consumer.stop()
    assert consumer.started is False


@pytest.mark.asyncio
async def test_listen_loop_dispatches_pmessage_to_callback() -> None:
    """Pmessage в listen() → JSON parse → callback вызван с dict."""
    pubsub = _make_pubsub_mock()

    # Симулируем один pmessage.
    message = {
        "type": "pmessage",
        "channel": b"hitl:resolved:t-1",
        "data": json.dumps(
            {
                "signal_id": "s-1",
                "workflow_id": "wf-1",
                "tenant_id": "t-1",
                "action": "approve",
                "resolved_by": "alice",
                "event_type": "hitl.resolved",
            }
        ),
    }

    # listen() — async iterator yielding one message then exit.
    async def fake_listen():
        yield message

    pubsub.listen = fake_listen
    wrapper = _make_wrapper_mock(pubsub)

    seen: list[dict] = []

    async def on_message(payload: dict) -> None:
        seen.append(payload)

    consumer = HitlPubSubConsumer()
    with patch(
        "src.backend.infrastructure.clients.storage.redis.get_redis_client",
        return_value=wrapper,
    ):
        result = await consumer.start(on_message=on_message)

    assert result is True
    # Даём listen loop'у шанс обработать message.
    await asyncio.sleep(0.1)
    await consumer.stop()

    assert len(seen) == 1
    assert seen[0]["signal_id"] == "s-1"
    assert seen[0]["action"] == "approve"


@pytest.mark.asyncio
async def test_callback_exception_does_not_kill_loop() -> None:
    """Если callback raises — loop продолжает работать на следующий message."""
    pubsub = _make_pubsub_mock()

    call_count = 0

    async def fake_listen():
        nonlocal call_count
        for i in range(2):
            call_count += 1
            yield {
                "type": "pmessage",
                "channel": b"hitl:resolved:t-1",
                "data": json.dumps({"signal_id": f"s-{i}", "event_type": "hitl.resolved"}),
            }

    pubsub.listen = fake_listen
    wrapper = _make_wrapper_mock(pubsub)

    async def flaky_on_message(payload: dict) -> None:
        if payload["signal_id"] == "s-0":
            raise RuntimeError("boom")
        # s-1 доходит нормально.

    consumer = HitlPubSubConsumer()
    with patch(
        "src.backend.infrastructure.clients.storage.redis.get_redis_client",
        return_value=wrapper,
    ):
        result = await consumer.start(on_message=flaky_on_message)

    assert result is True
    await asyncio.sleep(0.1)
    await consumer.stop()

    assert call_count == 2  # оба message прочитаны, не только s-0.


@pytest.mark.asyncio
async def test_malformed_message_skipped() -> None:
    """Невалидный JSON → warning + skip (loop продолжает)."""
    pubsub = _make_pubsub_mock()

    async def fake_listen():
        yield {
            "type": "pmessage",
            "channel": b"hitl:resolved:t-1",
            "data": b"{not valid json",
        }

    pubsub.listen = fake_listen
    wrapper = _make_wrapper_mock(pubsub)

    seen: list[dict] = []

    async def on_message(payload: dict) -> None:
        seen.append(payload)

    consumer = HitlPubSubConsumer()
    with patch(
        "src.backend.infrastructure.clients.storage.redis.get_redis_client",
        return_value=wrapper,
    ):
        result = await consumer.start(on_message=on_message)

    assert result is True
    await asyncio.sleep(0.1)
    await consumer.stop()

    assert seen == []  # malformed skipped


@pytest.mark.asyncio
async def test_stop_is_idempotent() -> None:
    """stop() можно вызывать несколько раз без ошибок."""
    consumer = HitlPubSubConsumer()
    # Без start() — также идемпотентно.
    await consumer.stop()
    await consumer.stop()
    assert consumer.started is False


@pytest.mark.asyncio
async def test_double_start_returns_true_without_respawning() -> None:
    """Повторный start() при running → return True без нового psubscribe."""
    pubsub = _make_pubsub_mock()
    wrapper = _make_wrapper_mock(pubsub)

    consumer = HitlPubSubConsumer()

    async def on_message(msg: dict) -> None:
        pass

    with patch(
        "src.backend.infrastructure.clients.storage.redis.get_redis_client",
        return_value=wrapper,
    ):
        first = await consumer.start(on_message=on_message)
        second = await consumer.start(on_message=on_message)

    assert first is True
    assert second is True
    # psubscribe вызывался только один раз (первый start).
    assert pubsub.psubscribe.await_count == 1
    await consumer.stop()
