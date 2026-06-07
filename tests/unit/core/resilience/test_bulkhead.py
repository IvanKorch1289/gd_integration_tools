"""Unit tests for Bulkhead pattern."""

# ruff: noqa: S101

from __future__ import annotations

import pytest

from src.backend.core.resilience.bulkhead import Bulkhead, get_bulkhead


class TestBulkhead:
    @pytest.fixture
    def bulkhead(self) -> Bulkhead:
        return Bulkhead()

    @pytest.mark.asyncio
    async def test_acquire_and_release(self, bulkhead: Bulkhead) -> None:
        bulkhead.register("svc1", max_concurrent=2)
        assert await bulkhead.acquire("svc1")
        bulkhead.release("svc1")
        stats = bulkhead.stats()
        assert stats["svc1"]["available"] == 2

    @pytest.mark.asyncio
    async def test_acquire_auto_register(self, bulkhead: Bulkhead) -> None:
        assert await bulkhead.acquire("auto_svc")
        bulkhead.release("auto_svc")
        assert "auto_svc" in bulkhead.stats()

    @pytest.mark.asyncio
    async def test_acquire_timeout(self, bulkhead: Bulkhead) -> None:
        bulkhead.register("svc2", max_concurrent=1)
        assert await bulkhead.acquire("svc2")
        # Second acquire should timeout quickly
        assert await bulkhead.acquire("svc2", timeout=0.01) is False
        bulkhead.release("svc2")

    def test_release_unknown_service(self, bulkhead: Bulkhead) -> None:
        # Should not raise
        bulkhead.release("unknown")

    def test_stats(self, bulkhead: Bulkhead) -> None:
        bulkhead.register("svc3", max_concurrent=5)
        stats = bulkhead.stats()
        assert stats["svc3"]["available"] == 5
        assert stats["svc3"]["locked"] is False

    def test_get_bulkhead_singleton(self) -> None:
        b1 = get_bulkhead()
        b2 = get_bulkhead()
        assert b1 is b2
