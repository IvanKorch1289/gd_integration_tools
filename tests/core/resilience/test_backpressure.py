"""Tests for backpressure module (E.3)."""

import asyncio
import pytest


class TestAdaptiveBulkhead:
    """Tests for AdaptiveBulkhead (bug B.3 fixed)."""

    @pytest.mark.asyncio
    async def test_acquire_timeout_no_leak(self):
        """Calling acquire with very small timeout does not leak semaphore.

        Bug B.3: without the `acquired = False` initialization, if CancelledError
        arrived during `wait_for` after the slot was already acquired but before
        `acquired = True` was set, the semaphore would leak (not released).

        We test the no-leak scenario by: (1) taking the only slot, (2) trying
        to acquire the second slot with tiny timeout (immediately fails),
        (3) verifying the slot is still available.
        """
        from src.backend.core.resilience.backpressure import AdaptiveBulkhead

        bulkhead = AdaptiveBulkhead(
            min_concurrent=1, max_concurrent=1, initial_concurrent=1
        )

        # Take the only slot
        result1 = await bulkhead.acquire(timeout=None)
        assert result1 is True
        assert bulkhead._in_flight == 1

        # Semaphore is full, try to acquire with tiny timeout → immediate TimeoutError
        # Bug B.3 would cause a leak here (the CancelledError handler incorrectly
        # releases the semaphore even though we never acquired it)
        result2 = await bulkhead.acquire(timeout=0.0)
        assert result2 is False
        assert bulkhead._in_flight == 1  # still 1, no leak

        # Verify semaphore still works: release and re-acquire
        bulkhead.release()
        assert bulkhead._in_flight == 0

        result3 = await bulkhead.acquire(timeout=1.0)
        assert result3 is True
        assert bulkhead._in_flight == 1

        # cleanup
        bulkhead.release()

    @pytest.mark.asyncio
    async def test_acquire_success(self):
        """Successful acquire increments _in_flight."""
        from src.backend.core.resilience.backpressure import AdaptiveBulkhead

        bulkhead = AdaptiveBulkhead(
            min_concurrent=2, max_concurrent=10, initial_concurrent=5
        )

        assert bulkhead._in_flight == 0

        result = await bulkhead.acquire(timeout=None)
        assert result is True
        assert bulkhead._in_flight == 1

        result2 = await bulkhead.acquire(timeout=None)
        assert result2 is True
        assert bulkhead._in_flight == 2

        # cleanup
        bulkhead.release()
        bulkhead.release()
        assert bulkhead._in_flight == 0
