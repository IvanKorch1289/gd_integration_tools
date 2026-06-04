"""Tests for src.backend.core.tenancy.quotas."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from src.backend.core.tenancy.quotas import QuotaExceeded, QuotaTracker


class TestQuotaTracker:
    @pytest.fixture
    def tracker(self) -> QuotaTracker:
        return QuotaTracker()

    @pytest.mark.asyncio
    async def test_consume_within_limit(self, tracker: QuotaTracker) -> None:
        raw = AsyncMock()
        raw._raw_client = None
        raw.incrby = AsyncMock(return_value=1)
        raw.expire = AsyncMock()
        with patch(
            "src.backend.infrastructure.clients.storage.redis.redis_client", raw
        ):
            result = await tracker.consume(
                "t1", "res", units=1, limit=10, period_seconds=60
            )
        assert result["remaining"] == 9
        assert result["limit"] == 10

    @pytest.mark.asyncio
    async def test_exceed_raises(self, tracker: QuotaTracker) -> None:
        raw = AsyncMock()
        raw._raw_client = None
        raw.incrby = AsyncMock(return_value=11)
        raw.expire = AsyncMock()
        with patch(
            "src.backend.infrastructure.clients.storage.redis.redis_client", raw
        ):
            with pytest.raises(QuotaExceeded):
                await tracker.consume("t1", "res", units=1, limit=10, period_seconds=60)

    @pytest.mark.asyncio
    async def test_redis_fail_open(self, tracker: QuotaTracker) -> None:
        raw = AsyncMock()
        raw._raw_client = None
        raw.incrby = AsyncMock(side_effect=ConnectionError("boom"))
        with patch(
            "src.backend.infrastructure.clients.storage.redis.redis_client", raw
        ):
            result = await tracker.consume(
                "t1", "res", units=1, limit=10, period_seconds=60
            )
        assert result["remaining"] == 9
