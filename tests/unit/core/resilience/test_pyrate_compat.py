"""Unit tests for src.backend.core.resilience._pyrate_compat."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest
from pyrate_limiter import Rate, RateItem

from src.backend.core.resilience._pyrate_compat import (
    BoundedInMemoryBucket,
    shutdown_pyrate_leaker,
)


class TestBoundedInMemoryBucket:
    def test_put_accepted(self) -> None:
        bucket = BoundedInMemoryBucket([Rate(10, 1)], max_items=5)
        item = RateItem(name="t", timestamp=1, weight=1)
        assert bucket.put(item) is True
        assert len(bucket.items) == 1

    def test_put_trims_overflow(self) -> None:
        bucket = BoundedInMemoryBucket([Rate(10, 1)], max_items=3)
        for i in range(5):
            item = RateItem(name="t", timestamp=i, weight=1)
            bucket.put(item)
        assert len(bucket.items) == 3
        assert bucket.items[0].timestamp == 2

    def test_stats(self) -> None:
        bucket = BoundedInMemoryBucket([Rate(10, 1)], max_items=10)
        for i in range(5):
            item = RateItem(name="t", timestamp=i, weight=1)
            bucket.put(item)
        stats = bucket.stats()
        assert stats["items"] == 5
        assert stats["max_items"] == 10
        assert stats["saturation"] == 0.5


class TestShutdownPyrateLeaker:
    @pytest.mark.asyncio
    async def test_no_leaker(self) -> None:
        limiter = MagicMock()
        limiter._leaker = None
        limiter.bucket_factory = None
        await shutdown_pyrate_leaker(limiter)
        assert limiter._leaker is None

    @pytest.mark.asyncio
    async def test_task_already_done(self) -> None:
        limiter = MagicMock()
        leaker = MagicMock()
        leaker.aio_leak_task = MagicMock()
        leaker.aio_leak_task.done.return_value = True
        limiter._leaker = leaker
        await shutdown_pyrate_leaker(limiter)
        leaker.aio_leak_task.cancel.assert_not_called()

    @pytest.mark.asyncio
    async def test_cancels_running_task(self) -> None:
        limiter = MagicMock()
        leaker = MagicMock()
        task = asyncio.create_task(asyncio.sleep(0.01))
        leaker.aio_leak_task = task
        limiter._leaker = leaker
        await shutdown_pyrate_leaker(limiter)
        assert task.cancelled() or task.done()
