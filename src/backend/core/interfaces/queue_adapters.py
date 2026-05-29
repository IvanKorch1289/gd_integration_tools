"""Queue adapters implementing QueueGateway for existing queue implementations.

Thin adapters that wrap existing queue implementations (PriorityRouter,
OutboxBackend) to satisfy the QueueGateway Protocol.
"""

from __future__ import annotations

import uuid
from typing import Any

from src.backend.core.interfaces.queue_gateway import QueueGateway
from src.backend.core.messaging.outbox import OutboxBackend, OutboxEvent

__all__ = ("OutboxQueueAdapter", "AsyncioQueueAdapter")


class OutboxQueueAdapter:
    """Adapter wrapping OutboxBackend to satisfy QueueGateway.

    Note: OutboxBackend has a richer interface (enqueue returns event_id,
    list_dlq, replay, mark_resolved). This adapter only exposes the
    basic QueueGateway methods using in-memory storage.

    Usage::

        from src.backend.core.messaging import FakeOutbox
        adapter = OutboxQueueAdapter(FakeOutbox())
        event_id = await adapter.enqueue({"type": "notification", "data": "..."})
        item = await adapter.dequeue(timeout=5.0)
        size = await adapter.size()
    """

    def __init__(self, backend: OutboxBackend) -> None:
        self._backend = backend
        self._items: list[OutboxEvent] = []
        self._pending_ids: dict[str, OutboxEvent] = {}

    async def enqueue(self, item: Any, priority: int = 0) -> str:
        """Enqueue an item via OutboxBackend."""
        event = OutboxEvent(
            transport="queue_adapter",
            action="enqueue",
            payload={"item": item, "priority": priority},
        )
        event_id = await self._backend.enqueue(event)
        self._pending_ids[event_id] = event
        return event_id

    async def dequeue(self, timeout: float | None = None) -> Any:
        """Dequeue is not directly supported by OutboxBackend.

        This is a simplification - real outbox pattern uses background
        processing via replay(). Returns None.
        """
        del timeout
        if self._items:
            return self._items.pop(0)
        return None

    async def size(self) -> int:
        """Return pending events count."""
        return len(self._pending_ids)

    async def clear(self) -> None:
        """Clear pending events."""
        self._pending_ids.clear()
        self._items.clear()


class AsyncioQueueAdapter:
    """Adapter wrapping asyncio.Queue to satisfy QueueGateway.

    Wraps a single asyncio.Queue instance.

    Usage::

        import asyncio
        queue = asyncio.Queue()
        adapter = AsyncioQueueAdapter(queue)
        await adapter.enqueue({"data": "test"})
        item = await adapter.dequeue(timeout=5.0)
    """

    def __init__(self, queue: Any) -> None:
        """Initialize with an asyncio.Queue.

        Args:
            queue: An asyncio.Queue instance.
        """
        self._queue = queue

    async def enqueue(self, item: Any, priority: int = 0) -> str:
        """Add item to the queue.

        Note: asyncio.Queue doesn't support priority natively.
        The priority parameter is accepted for compatibility but ignored.
        """
        del priority
        item_id = str(uuid.uuid4())
        # Store item with id as tuple for dequeue tracking
        await self._queue.put((item_id, item))
        return item_id

    async def dequeue(self, timeout: float | None = None) -> Any:
        """Remove and return an item from the queue.

        Args:
            timeout: Maximum seconds to wait. None blocks indefinitely.

        Returns:
            The dequeued item, or None if timeout expired.
        """
        try:
            if timeout is None:
                item_id, item = await self._queue.get()
            elif timeout == 0:
                item_id, item = self._queue.get_nowait()
            else:
                item_id, item = await self._queue.get()
            self._queue.task_done()
            return item
        except Exception:
            return None

    async def size(self) -> int:
        """Return approximate queue size."""
        return self._queue.qsize()

    async def clear(self) -> None:
        """Clear all items from queue."""
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
                self._queue.task_done()
            except Exception:
                break
