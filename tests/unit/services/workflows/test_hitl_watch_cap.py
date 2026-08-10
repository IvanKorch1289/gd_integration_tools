"""D-A8-11 fix (cycle 1): WatchError retry-loop без iteration cap — DoS vector.

Ранее _mark_resolved_transactional использовал bare 'while True: ... continue'
без iteration cap. Persistent contention приводил к tight loop → CPU
saturation (DoS vector).

Фикс: max_watch_retries (default 10) + HITLWatchContentionError при
превышении. Caller должен retry с backoff или escalate.
"""


from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.backend.services.workflows.hitl_signal_store_redis import (
    HITLWatchContentionError,
    RedisHitlSignalStore,
)


def _make_signal_data() -> dict[str, Any]:
    return {
        "signal_id": "test-signal",
        "tenant_id": "tenant-1",
        "created_at": "2026-08-07T08:00:00+00:00",
        "resolved_at": None,
        "is_resolved": False,
    }


class TestHITLWatchCap:
    """D-A8-11 fix (cycle 1): WatchError retry-loop iteration cap."""

    @pytest.mark.asyncio
    async def test_default_max_watch_retries(self) -> None:
        """Default max_watch_retries = 10."""
        store = RedisHitlSignalStore()
        assert store._max_watch_retries == 10

    @pytest.mark.asyncio
    async def test_custom_max_watch_retries(self) -> None:
        """Custom max_watch_retries через __init__."""
        store = RedisHitlSignalStore(max_watch_retries=3)
        assert store._max_watch_retries == 3

    @pytest.mark.asyncio
    async def test_persistent_contention_raises_hitl_watch_error(self) -> None:
        """Persistent WATCH conflict (всегда WatchError) → HITLWatchContentionError.

        D-A8-11 fix: explicit cap предотвращает tight loop DoS.
        """
        from redis.exceptions import WatchError

        # Mock pipeline с persistent WATCH conflict
        mock_pipe = MagicMock()
        mock_pipe.watch = AsyncMock()
        mock_pipe.unwatch = AsyncMock()
        mock_pipe.multi = MagicMock()
        mock_pipe.hset = MagicMock()

        # hget → возвращает signal data; затем pipe.execute() raises WatchError
        mock_pipe.hget = AsyncMock(return_value=json.dumps(_make_signal_data()))
        mock_pipe.execute = AsyncMock(side_effect=WatchError("persistent conflict"))

        mock_client = MagicMock()
        mock_client.pipeline = MagicMock()
        mock_client.pipeline.return_value.__aenter__ = AsyncMock(return_value=mock_pipe)
        mock_client.pipeline.return_value.__aexit__ = AsyncMock(return_value=None)

        store = RedisHitlSignalStore(
            redis_client=mock_client,
            max_watch_retries=3,  # low cap для теста
        )

        with pytest.raises(HITLWatchContentionError) as exc_info:
            await store._mark_resolved_transactional(
                mock_client,
                "test-signal",
                action="approve",
                resolved_by="user-1",
            )

        # Error message содержит signal_id + retries info
        assert "test-signal" in str(exc_info.value)
        assert "3 retries" in str(exc_info.value)
        # pipe.watch вызван max_watch_retries (3) раз до raise на 4-й итерации
        assert mock_pipe.watch.await_count == 3

    @pytest.mark.asyncio
    async def test_normal_completion_no_watch_error(self) -> None:
        """Normal completion (без WatchError) → succeed."""
        mock_pipe = MagicMock()
        mock_pipe.watch = AsyncMock()
        mock_pipe.unwatch = AsyncMock()
        mock_pipe.multi = MagicMock()
        mock_pipe.hset = MagicMock()

        signal_data = _make_signal_data()
        mock_pipe.hget = AsyncMock(return_value=json.dumps(signal_data))
        mock_pipe.execute = AsyncMock(return_value=True)

        mock_client = MagicMock()
        mock_client.pipeline = MagicMock()
        mock_client.pipeline.return_value.__aenter__ = AsyncMock(return_value=mock_pipe)
        mock_client.pipeline.return_value.__aexit__ = AsyncMock(return_value=None)

        store = RedisHitlSignalStore(redis_client=mock_client)

        result = await store._mark_resolved_transactional(
            mock_client,
            "test-signal",
            action="approve",
            resolved_by="user-1",
        )

        assert result["resolved_at"] is not None
        assert result["resolved_action"] == "approve"
