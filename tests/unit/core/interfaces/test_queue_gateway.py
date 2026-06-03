"""Unit tests for src.backend.core.interfaces.queue_gateway."""

from __future__ import annotations

from src.backend.core.interfaces.queue_gateway import QueueGateway


class TestQueueGateway:
    def test_is_runtime_checkable(self) -> None:
        class Fake:
            async def enqueue(self, item: object, priority: int = 0) -> str:
                return ""

            async def dequeue(self, timeout: float | None = None) -> object:
                return None

            async def size(self) -> int:
                return 0

            async def clear(self) -> None:
                pass

        assert isinstance(Fake(), QueueGateway)

    def test_missing_method_fails(self) -> None:
        class Bad:
            async def enqueue(self, item: object, priority: int = 0) -> str:
                return ""

        assert not isinstance(Bad(), QueueGateway)
