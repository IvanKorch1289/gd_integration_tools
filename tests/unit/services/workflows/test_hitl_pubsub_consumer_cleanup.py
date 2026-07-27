"""Regression test: ``HitlPubSubConsumer.stop`` no longer binds an
unused ``callback`` local (F841). We verify the public lifecycle still
works: stop is idempotent and clears the consumer state."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.backend.services.workflows.hitl_pubsub_consumer import (
    HitlPubSubConsumer,
)


class _FakePubsub:
    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class TestHitlPubSubConsumerStop:
    @pytest.mark.asyncio
    async def test_stop_clears_state_and_closes_pubsub(self) -> None:
        consumer = HitlPubSubConsumer()
        pubsub = _FakePubsub()
        consumer._pubsub = pubsub  # type: ignore[attr-defined]
        consumer._on_message = AsyncMock()  # type: ignore[attr-defined]
        task = MagicMock()
        task.done.return_value = True
        consumer._task = task  # type: ignore[attr-defined]

        await consumer.stop()

        assert consumer._pubsub is None
        assert consumer._on_message is None
        assert pubsub.closed is True

    @pytest.mark.asyncio
    async def test_stop_is_idempotent(self) -> None:
        consumer = HitlPubSubConsumer()
        await consumer.stop()
        # Second call must not raise even though state was already cleared.
        await consumer.stop()
        assert consumer._pubsub is None
        assert consumer._on_message is None
