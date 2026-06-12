"""Tests для PollCDCBackend S93 W4 — feed mode (in-memory CDC)."""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import pytest

from src.backend.core.cdc.source import CDCCursor, CDCEvent
from src.backend.infrastructure.cdc.poll_backend import PollCDCBackend


async def _make_feed(items: list[dict[str, Any]]):
    """Async generator из list для feed injection."""
    for item in items:
        yield item


@pytest.mark.asyncio
async def test_poll_cdc_feed_mode_basic() -> None:
    """Feed mode: dicts → CDCEvent с UPSERT."""
    feed = _make_feed(
        [
            {
                "table": "users",
                "new": {"id": 1, "name": "Alice"},
                "cursor": "2025-01-01T00:00:00Z",
            },
            {
                "table": "users",
                "new": {"id": 2, "name": "Bob"},
                "cursor": "2025-01-01T00:00:01Z",
            },
        ]
    )
    backend = PollCDCBackend(profile="test", feed=feed)
    events: list[CDCEvent] = []
    async for evt in backend.subscribe(tables=["users"]):
        events.append(evt)

    assert len(events) == 2
    assert events[0].operation == "UPSERT"
    assert events[0].source == "poll:test"
    assert events[0].table == "users"
    assert events[0].new == {"id": 1, "name": "Alice"}
    assert events[0].cursor.value == "2025-01-01T00:00:00Z"
    assert events[1].cursor.value == "2025-01-01T00:00:01Z"


@pytest.mark.asyncio
async def test_poll_cdc_feed_skips_non_dict() -> None:
    """Non-dict entries в feed → skip (warning)."""
    feed = _make_feed(
        [
            {"table": "t1", "new": {"v": 1}},
            "not-a-dict",  # type: ignore[list-item]
            {"table": "t1", "new": {"v": 2}},
        ]
    )
    backend = PollCDCBackend(profile="test", feed=feed)
    events: list[CDCEvent] = []
    async for evt in backend.subscribe(tables=["t1"]):
        events.append(evt)

    assert len(events) == 2  # non-dict skipped
    assert events[0].new == {"v": 1}
    assert events[1].new == {"v": 2}


@pytest.mark.asyncio
async def test_poll_cdc_feed_respects_stop() -> None:
    """backend.close() во время feed consume → stop."""
    async def slow_feed():
        for i in range(10):
            await asyncio.sleep(0.01)
            yield {"table": "t", "new": {"i": i}}

    backend = PollCDCBackend(profile="test", feed=slow_feed())
    events: list[CDCEvent] = []

    async def consume_then_stop():
        async for evt in backend.subscribe(tables=["t"]):
            events.append(evt)
            if len(events) >= 2:
                await backend.close()

    await asyncio.wait_for(consume_then_stop(), timeout=1.0)
    assert len(events) <= 2  # остановились после 2


@pytest.mark.asyncio
async def test_poll_cdc_ack_appends_cursor() -> None:
    """ack() добавляет cursor в _cursor_log."""
    backend = PollCDCBackend(profile="test")
    cursor = CDCCursor(value="cur-1", backend="poll")
    await backend.ack(cursor)
    await backend.ack(CDCCursor(value="cur-2", backend="poll"))
    assert len(backend._cursor_log) == 2
    assert backend._cursor_log[0] == cursor


@pytest.mark.asyncio
async def test_poll_cdc_replay_feed_mode() -> None:
    """replay() в feed mode re-consume'ит feed."""
    feed = _make_feed([{"table": "t", "new": {"v": 1}}])
    backend = PollCDCBackend(profile="test", feed=feed)
    events: list[CDCEvent] = []
    async for evt in backend.replay(
        start_cursor=CDCCursor(value="start", backend="poll")
    ):
        events.append(evt)
    assert len(events) == 1
    assert events[0].source == "poll:test:replay"
    assert events[0].new == {"v": 1}


@pytest.mark.asyncio
async def test_poll_cdc_close_sets_stopped() -> None:
    """close() устанавливает stopped event."""
    backend = PollCDCBackend(profile="test")
    assert not backend._stopped.is_set()
    await backend.close()
    assert backend._stopped.is_set()


@pytest.mark.asyncio
async def test_poll_cdc_polling_scaffold_no_events() -> None:
    """Polling mode (scaffold) генерирует no events (Wave R3)."""
    backend = PollCDCBackend(profile="test", interval_s=0.01)
    events: list[CDCEvent] = []

    async def consume_with_timeout():
        async for evt in backend.subscribe(tables=["t"]):
            events.append(evt)
            if len(events) > 0:
                break  # safety

    task = asyncio.create_task(consume_with_timeout())
    await asyncio.sleep(0.05)  # дать polling-loop покрутиться
    await backend.close()
    try:
        await asyncio.wait_for(task, timeout=1.0)
    except asyncio.TimeoutError:
        task.cancel()
    # Scaffold не yield'ит события — events должен быть пуст
    assert events == []
