"""Tests for src.backend.core.tenancy.quotas."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.backend.core.tenancy.quotas import QuotaExceeded, QuotaTracker


def _make_raw() -> AsyncMock:
    raw = AsyncMock()
    raw._raw_client = None
    return raw


class TestQuotaTracker:
    @pytest.fixture
    def tracker(self) -> QuotaTracker:
        return QuotaTracker()

    @pytest.mark.asyncio
    async def test_consume_within_limit(
        self, tracker: QuotaTracker, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        raw = _make_raw()
        raw.incrby = AsyncMock(return_value=1)
        raw.expire = AsyncMock()
        import src.backend.infrastructure.clients.storage.redis as redis_mod
        monkeypatch.setattr(redis_mod, "get_redis_client", lambda: raw)
        result = await tracker.consume(
            "t1", "res", units=1, limit=10, period_seconds=60
        )
        assert result["remaining"] == 9
        assert result["limit"] == 10

    @pytest.mark.asyncio
    async def test_exceed_raises(
        self, tracker: QuotaTracker, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        raw = _make_raw()
        raw.incrby = AsyncMock(return_value=11)
        raw.expire = AsyncMock()
        import src.backend.infrastructure.clients.storage.redis as redis_mod
        monkeypatch.setattr(redis_mod, "get_redis_client", lambda: raw)
        with pytest.raises(QuotaExceeded):
            await tracker.consume("t1", "res", units=1, limit=10, period_seconds=60)

    @pytest.mark.asyncio
    async def test_redis_fail_open(
        self, tracker: QuotaTracker, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        raw = _make_raw()
        raw.incrby = AsyncMock(side_effect=ConnectionError("boom"))
        import src.backend.infrastructure.clients.storage.redis as redis_mod
        monkeypatch.setattr(redis_mod, "get_redis_client", lambda: raw)
        result = await tracker.consume(
            "t1", "res", units=1, limit=10, period_seconds=60
        )
        assert result["remaining"] == 9
