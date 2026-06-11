"""Unit tests for UnifiedPoolManager (S37.2)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.infrastructure.clients.unified_pool_manager import (
    UnifiedPoolManager,
    get_unified_pool_manager,
)


@pytest.fixture(autouse=True)
def _reset_singleton():
    """Reset singleton state between tests."""
    from src.backend.infrastructure.clients import unified_pool_manager

    unified_pool_manager._manager_instance = None
    yield
    unified_pool_manager._manager_instance = None


class TestUnifiedPoolManager:
    @pytest.mark.asyncio
    async def test_register_and_list(self) -> None:
        mgr = UnifiedPoolManager()
        ping = AsyncMock()
        mgr.register(
            "db_main", MagicMock(), ping_fn=ping, kind="sqlalchemy", max_size=10
        )
        assert mgr.list_pools() == ["db_main"]
        reg = mgr._pools["db_main"]
        assert reg.name == "db_main"
        assert reg.kind == "sqlalchemy"
        assert reg.max_size == 10

    @pytest.mark.asyncio
    async def test_unregister(self) -> None:
        mgr = UnifiedPoolManager()
        ping = AsyncMock()
        mgr.register("redis", MagicMock(), ping_fn=ping)
        mgr.unregister("redis")
        assert mgr.list_pools() == []

    @pytest.mark.asyncio
    async def test_health_check_all_ok(self) -> None:
        mgr = UnifiedPoolManager()
        ping = AsyncMock()
        mgr.register("db", MagicMock(), ping_fn=ping, kind="sqlalchemy")
        result = await mgr.health_check_all(mode="fast")
        assert result["status"] == "ok"
        assert result["pools"]["db"]["status"] == "ok"
        ping.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_health_check_all_error(self) -> None:
        mgr = UnifiedPoolManager()
        ping_ok = AsyncMock()
        ping_fail = AsyncMock(side_effect=ConnectionError("boom"))
        mgr.register("db", MagicMock(), ping_fn=ping_ok, kind="sqlalchemy")
        mgr.register("redis", MagicMock(), ping_fn=ping_fail, kind="redis")
        result = await mgr.health_check_all(mode="fast")
        assert result["status"] == "down"
        assert result["pools"]["db"]["status"] == "ok"
        assert result["pools"]["redis"]["status"] == "error"

    @pytest.mark.asyncio
    async def test_health_check_timeout(self) -> None:
        mgr = UnifiedPoolManager()
        event = asyncio.Event()
        ping_slow = AsyncMock(side_effect=event.wait)
        mgr.register("slow", MagicMock(), ping_fn=ping_slow)
        result = await mgr.health_check_all(mode="fast", timeout=0.01)
        assert result["pools"]["slow"]["status"] == "error"
        assert "timeout" in result["pools"]["slow"]["error"]

    @pytest.mark.asyncio
    async def test_get_metrics_sqlalchemy(self) -> None:
        mgr = UnifiedPoolManager()
        pool = MagicMock()
        pool.size.return_value = 10
        pool.checkedin.return_value = 3
        pool.checkedout.return_value = 5
        pool.overflow.return_value = 2
        mgr.register("db", pool, ping_fn=AsyncMock(), kind="sqlalchemy")
        metrics = await mgr.get_metrics()
        assert metrics["db"]["size"] == 10
        assert metrics["db"]["checked_out"] == 5
        assert metrics["db"]["utilization_pct"] == 50.0

    @pytest.mark.asyncio
    async def test_warmup_all_fallback_ping(self) -> None:
        mgr = UnifiedPoolManager()
        ping = AsyncMock()
        mgr.register("db", MagicMock(), ping_fn=ping, kind="sqlalchemy")
        # PoolWarmup is imported inside warmup_all from database.pool_warmup
        mock_warmup_cls = MagicMock()
        mock_warmup_cls.return_value.warmup_postgres = AsyncMock()
        with patch(
            "src.backend.infrastructure.database.pool_warmup.PoolWarmup",
            mock_warmup_cls,
        ):
            result = await mgr.warmup_all()
        assert result["db"] == "ok"
        ping.assert_not_awaited()  # sqlalchemy branch uses PoolWarmup.warmup_postgres

        # Fallback ping when PoolWarmup is unavailable
        mgr2 = UnifiedPoolManager()
        ping2 = AsyncMock()
        mgr2.register("other", MagicMock(), ping_fn=ping2, kind="other")
        with patch(
            "src.backend.infrastructure.database.pool_warmup.PoolWarmup",
            side_effect=ImportError,
        ):
            result2 = await mgr2.warmup_all()
        assert result2["other"] == "ok"
        ping2.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_start_stop_monitors_no_crash(self) -> None:
        mgr = UnifiedPoolManager()
        # Without any pools registered, start/stop should not crash
        await mgr.start_monitors()
        await mgr.stop_monitors()

    @pytest.mark.asyncio
    async def test_singleton(self) -> None:
        a = get_unified_pool_manager()
        b = get_unified_pool_manager()
        assert a is b
