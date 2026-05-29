"""QueueGateway — generic Protocol for queue operations.

This module defines a unified Protocol for queue implementations across
the codebase (NotificationGateway, OutboxBackend, etc.).
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

__all__ = ("QueueGateway",)


@runtime_checkable
class QueueGateway(Protocol):
    """Generic queue Protocol for enqueue/dequeue operations.

    Provides a unified interface for queue implementations across
    NotificationGateway (tx_queue, marketing_queue), OutboxBackend,
    and other queue-based components.

    Usage::

        async def process_queue(gateway: QueueGateway) -> None:
            item = await gateway.dequeue(timeout=5.0)
            if item is not None:
                # process item
                pass

        async def enqueue_item(gateway: QueueGateway, item: Any) -> str:
            return await gateway.enqueue(item, priority=0)
    """

    async def enqueue(self, item: Any, priority: int = 0) -> str:
        """Add an item to the queue.

        Args:
            item: The item to enqueue.
            priority: Priority level (higher values = higher priority).

        Returns:
            A unique identifier for the enqueued item.
        """
        ...

    async def dequeue(self, timeout: float | None = None) -> Any:
        """Remove and return an item from the queue.

        Args:
            timeout: Maximum seconds to wait for an item.
                None blocks indefinitely, 0 returns immediately.

        Returns:
            The dequeued item, or None if timeout expired.
        """
        ...

    async def size(self) -> int:
        """Return the approximate number of items in the queue.

        Returns:
            Current queue size.
        """
        ...

    async def clear(self) -> None:
        """Remove all items from the queue."""
        ...
