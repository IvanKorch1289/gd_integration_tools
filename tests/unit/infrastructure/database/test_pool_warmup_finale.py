"""Unit-тесты PoolWarmup HTTPX/Graylog + PoolReconnectMonitor (S13 K2 W7)."""

# ruff: noqa: S101

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock

import pytest

from src.backend.infrastructure.database.pool_warmup import (
    PoolReconnectMonitor,
    PoolWarmup,
)


@pytest.mark.asyncio
async def test_warmup_httpx_success() -> None:
    client = AsyncMock()
    client.head = AsyncMock(return_value=None)
    warmup = PoolWarmup()
    result = await warmup.warmup_httpx(client, "http://x.io/health", min_connections=3)
    assert "httpx" in result.warmed_pools
    assert not result.failed_pools
    assert client.head.await_count == 3


@pytest.mark.asyncio
async def test_warmup_httpx_failure_recorded() -> None:
    client = AsyncMock()
    client.head = AsyncMock(side_effect=ConnectionError("refused"))
    warmup = PoolWarmup()
    result = await warmup.warmup_httpx(client, "http://x.io/health", min_connections=2)
    assert "httpx" not in result.warmed_pools
    assert "httpx" in result.failed_pools


@pytest.mark.asyncio
async def test_warmup_graylog_uses_emit_keepalive() -> None:
    sink = AsyncMock()
    sink.emit_keepalive = AsyncMock()
    warmup = PoolWarmup()
    result = await warmup.warmup_graylog(sink, ping_count=2)
    assert "graylog" in result.warmed_pools
    assert sink.emit_keepalive.await_count == 2


@pytest.mark.asyncio
async def test_warmup_graylog_fallback_to_emit() -> None:
    class _Sink:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        async def emit(self, payload: dict[str, Any]) -> None:
            self.calls.append(payload)

    sink = _Sink()
    warmup = PoolWarmup()
    result = await warmup.warmup_graylog(sink, ping_count=2)
    assert "graylog" in result.warmed_pools
    assert len(sink.calls) == 2
    assert sink.calls[0]["_keepalive"] is True


@pytest.mark.asyncio
async def test_reconnect_monitor_calls_on_reconnect_after_recovery() -> None:
    state = {"healthy": True}

    async def _hc() -> bool:
        return state["healthy"]

    callback = AsyncMock()
    monitor = PoolReconnectMonitor(
        pools={"db": _hc}, on_reconnect=callback, interval_seconds=0.01
    )
    await monitor.start()
    state["healthy"] = False
    await asyncio.sleep(0.05)
    state["healthy"] = True
    await asyncio.sleep(0.05)
    await monitor.stop()
    callback.assert_awaited_with("db")


@pytest.mark.asyncio
async def test_reconnect_monitor_no_callback_on_steady_state() -> None:
    async def _hc() -> bool:
        return True

    callback = AsyncMock()
    monitor = PoolReconnectMonitor(
        pools={"db": _hc}, on_reconnect=callback, interval_seconds=0.01
    )
    await monitor.start()
    await asyncio.sleep(0.05)
    await monitor.stop()
    callback.assert_not_awaited()


@pytest.mark.asyncio
async def test_reconnect_monitor_healthcheck_exception_is_unhealthy() -> None:
    async def _hc() -> bool:
        raise RuntimeError("boom")

    callback = AsyncMock()
    monitor = PoolReconnectMonitor(
        pools={"db": _hc}, on_reconnect=callback, interval_seconds=0.01
    )
    await monitor.start()
    await asyncio.sleep(0.05)
    await monitor.stop()
    # При первом исключении статус становится unhealthy, callback не зовётся.
    callback.assert_not_awaited()
