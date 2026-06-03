"""Unit tests for src.backend.core.interfaces.queue_adapters."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from src.backend.core.interfaces.queue_adapters import (
    AsyncioQueueAdapter,
    OutboxQueueAdapter,
)
from src.backend.core.messaging.outbox import OutboxBackend, OutboxEvent


class FakeOutbox(OutboxBackend):
    """Fake OutboxBackend for testing."""

    def __init__(self) -> None:
        self._events: list[OutboxEvent] = []

    async def enqueue(self, event: OutboxEvent) -> str:
        self._events.append(event)
        return f"evt-{len(self._events)}"

    async def list_dlq(self, *, limit: int = 100) -> list[OutboxEvent]:
        return []

    async def replay(self, event_id: str) -> bool:
        return True

    async def mark_resolved(self, event_id: str) -> bool:
        return True


class TestOutboxQueueAdapter:
    @pytest.mark.asyncio
    async def test_enqueue(self) -> None:
        backend = FakeOutbox()
        adapter = OutboxQueueAdapter(backend)
        event_id = await adapter.enqueue({"data": "x"}, priority=5)
        assert event_id.startswith("evt-")
        assert await adapter.size() == 1

    @pytest.mark.asyncio
    async def test_dequeue_returns_none_when_empty(self) -> None:
        backend = FakeOutbox()
        adapter = OutboxQueueAdapter(backend)
        assert await adapter.dequeue() is None

    @pytest.mark.asyncio
    async def test_clear(self) -> None:
        backend = FakeOutbox()
        adapter = OutboxQueueAdapter(backend)
        await adapter.enqueue({"data": "x"})
        await adapter.clear()
        assert await adapter.size() == 0


class TestAsyncioQueueAdapter:
    @pytest.mark.asyncio
    async def test_enqueue_dequeue(self) -> None:
        queue: asyncio.Queue[Any] = asyncio.Queue()
        adapter = AsyncioQueueAdapter(queue)
        await adapter.enqueue({"data": "x"})
        item = await adapter.dequeue()
        assert item == {"data": "x"}

    @pytest.mark.asyncio
    async def test_dequeue_timeout_zero_empty(self) -> None:
        queue: asyncio.Queue[Any] = asyncio.Queue()
        adapter = AsyncioQueueAdapter(queue)
        assert await adapter.dequeue(timeout=0) is None

    @pytest.mark.asyncio
    async def test_size(self) -> None:
        queue: asyncio.Queue[Any] = asyncio.Queue()
        adapter = AsyncioQueueAdapter(queue)
        await adapter.enqueue({"a": 1})
        await adapter.enqueue({"b": 2})
        assert await adapter.size() == 2

    @pytest.mark.asyncio
    async def test_clear(self) -> None:
        queue: asyncio.Queue[Any] = asyncio.Queue()
        adapter = AsyncioQueueAdapter(queue)
        await adapter.enqueue({"a": 1})
        await adapter.enqueue({"b": 2})
        await adapter.clear()
        assert await adapter.size() == 0
        assert await adapter.dequeue(timeout=0) is None
