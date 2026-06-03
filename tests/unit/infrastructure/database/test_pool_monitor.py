"""Unit tests for PoolMonitor."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.infrastructure.database.pool_monitor import (
    PoolMonitor,
    get_pool_monitor,
)


class TestPoolMonitor:
    """Tests for :class:`PoolMonitor`."""

    @pytest.fixture
    def monitor(self) -> PoolMonitor:
        return PoolMonitor(check_interval=1)

    @pytest.mark.asyncio
    async def test_start_creates_task(self, monitor: PoolMonitor) -> None:
        """start creates monitoring task."""
        mock_registry = MagicMock()
        mock_task = AsyncMock()
        mock_registry.create_task.return_value = mock_task

        with patch(
            "src.backend.infrastructure.database.pool_monitor.get_task_registry",
            return_value=mock_registry,
        ):
            await monitor.start()

        assert monitor._running is True
        mock_registry.create_task.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_cancels_task(self, monitor: PoolMonitor) -> None:
        """stop cancels the monitoring task."""
        mock_task: asyncio.Task[Any] = asyncio.get_event_loop().create_future()
        monitor._task = mock_task
        monitor._running = True

        await monitor.stop()

        assert mock_task.cancelled()
        assert monitor._running is False

    @pytest.mark.asyncio
    async def test_collect_stats(self, monitor: PoolMonitor) -> None:
        """collect_stats returns pool metrics."""
        mock_pool = MagicMock()
        mock_pool.checkedin.return_value = 5
        mock_pool.checkedout.return_value = 3
        mock_pool.overflow.return_value = 0
        mock_pool.size.return_value = 10

        mock_engine = MagicMock()
        mock_engine.pool = mock_pool

        mock_initializer = MagicMock()
        mock_initializer._async_engine = mock_engine

        with patch(
            "src.backend.infrastructure.database.database.db_initializer",
            mock_initializer,
            create=True,
        ):
            stats = await monitor.collect_stats()

        assert stats is not None
        assert stats["pool_size"] == 10
        assert stats["checked_in"] == 5
        assert stats["checked_out"] == 3
        assert stats["overflow"] == 0
        assert stats["total_connections"] == 8
        assert stats["utilization_pct"] == 30.0

    @pytest.mark.asyncio
    async def test_collect_stats_no_initializer(self, monitor: PoolMonitor) -> None:
        """collect_stats returns None when db_initializer is unavailable."""
        with patch(
            "src.backend.infrastructure.database.pool_monitor.db_initializer",
            None,
            create=True,
        ):
            stats = await monitor.collect_stats()

        assert stats is None

    def test_get_current_stats_empty(self, monitor: PoolMonitor) -> None:
        """get_current_stats returns no_data when history is empty."""
        assert monitor.get_current_stats() == {"status": "no_data"}

    def test_get_history(self, monitor: PoolMonitor) -> None:
        """get_history returns last N entries."""
        monitor._stats_history = [{"i": i} for i in range(10)]
        assert len(monitor.get_history(limit=3)) == 3
        assert monitor.get_history(limit=3)[-1] == {"i": 9}


class TestGetPoolMonitor:
    """Tests for get_pool_monitor."""

    def test_returns_pool_monitor(self) -> None:
        """get_pool_monitor returns a PoolMonitor instance."""
        pm = get_pool_monitor()
        assert isinstance(pm, PoolMonitor)
