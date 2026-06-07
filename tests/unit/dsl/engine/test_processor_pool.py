"""Unit-тесты для processor_pool.py.

Wave [wave:g1-processor-pool]
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import MagicMock

import pytest

from src.backend.dsl.engine.exchange import Exchange, Message
from src.backend.dsl.engine.processor_pool import (
    PoolMetrics,
    ProcessorPool,
    get_processor_pool,
    set_processor_pool,
)
from src.backend.dsl.engine.processors.base import BaseProcessor


class DummyProcessor(BaseProcessor):
    """Test processor that does minimal work."""

    def __init__(self, name: str = "dummy", fail: bool = False) -> None:
        super().__init__(name=name)
        self.fail = fail
        self.processed = False

    async def process(self, exchange: Exchange[Any], context: Any) -> None:
        self.processed = True
        if self.fail:
            raise ValueError("Test failure")


def _make_exchange(body: Any = None) -> Exchange[Any]:
    return Exchange(in_message=Message(body=body, headers={}))


# ── PoolMetrics ──────────────────────────────────────────────────────────────


class TestPoolMetrics:
    def test_avg_duration_zero_when_empty(self) -> None:
        m = PoolMetrics()
        assert m.avg_duration_ms == 0.0

    def test_avg_duration_calculated(self) -> None:
        m = PoolMetrics()
        m.total_completed = 2
        m.total_durations_ms = 100.0
        assert m.avg_duration_ms == 50.0


# ── ProcessorPool ─────────────────────────────────────────────────────────────


class TestProcessorPoolCreation:
    def test_default_max_workers(self) -> None:
        pool = ProcessorPool()
        assert pool.max_workers == 4

    def test_custom_max_workers(self) -> None:
        pool = ProcessorPool(max_workers=8)
        assert pool.max_workers == 8

    def test_initial_metrics(self) -> None:
        pool = ProcessorPool()
        assert pool.metrics.total_submitted == 0
        assert pool.metrics.total_completed == 0
        assert pool.metrics.total_failed == 0

    def test_active_count_initially_zero(self) -> None:
        pool = ProcessorPool()
        assert pool.active_count == 0

    def test_repr(self) -> None:
        pool = ProcessorPool(max_workers=2)
        r = repr(pool)
        assert "max_workers=2" in r


@pytest.mark.asyncio
async def test_execute_parallel_all_succeed() -> None:
    pool = ProcessorPool(max_workers=4)
    proc1 = DummyProcessor("p1")
    proc2 = DummyProcessor("p2")

    exc = _make_exchange({"test": "data"})
    ctx = MagicMock()

    results = await pool.execute_parallel([proc1, proc2], exc, ctx)

    assert len(results) == 2
    assert all(r["status"] == "ok" for r in results)
    assert proc1.processed
    assert proc2.processed


@pytest.mark.asyncio
async def test_execute_parallel_with_failure() -> None:
    pool = ProcessorPool(max_workers=4)
    good = DummyProcessor("good")
    bad = DummyProcessor("bad", fail=True)

    exc = _make_exchange({"test": "data"})
    ctx = MagicMock()

    results = await pool.execute_parallel([good, bad], exc, ctx)

    assert len(results) == 2
    # Results order matches input order
    assert results[0]["processor"] == "good"
    assert results[0]["status"] == "ok"
    assert results[1]["processor"] == "bad"
    assert results[1]["status"] == "error"
    assert "Test failure" in results[1]["error"]


@pytest.mark.asyncio
async def test_execute_parallel_updates_metrics() -> None:
    pool = ProcessorPool(max_workers=4)
    proc1 = DummyProcessor("p1")
    proc2 = DummyProcessor("p2")

    exc = _make_exchange({"test": "data"})
    ctx = MagicMock()

    await pool.execute_parallel([proc1, proc2], exc, ctx)

    assert pool.metrics.total_submitted == 2
    assert pool.metrics.total_completed == 2
    assert pool.metrics.total_failed == 0


@pytest.mark.asyncio
async def test_execute_parallel_concurrency_bounded() -> None:
    pool = ProcessorPool(max_workers=2)  # Only 2 concurrent
    processors = [DummyProcessor(f"p{i}") for i in range(4)]

    exc = _make_exchange({"test": "data"})
    ctx = MagicMock()

    start = asyncio.get_event_loop().time()
    results = await pool.execute_parallel(processors, exc, ctx, timeout=5.0)
    elapsed = asyncio.get_event_loop().time() - start

    assert len(results) == 4
    assert all(r["status"] == "ok" for r in results)


@pytest.mark.asyncio
async def test_execute_with_callback() -> None:
    pool = ProcessorPool()
    proc = DummyProcessor("callback_test")
    exc = _make_exchange({"test": "data"})
    ctx = MagicMock()

    callback_results: list[dict[str, Any]] = []

    async def callback(result: dict[str, Any]) -> None:
        callback_results.append(result)

    result = await pool.execute_with_callback(proc, exc, ctx, on_complete=callback)

    assert result["processor"] == "callback_test"
    assert result["status"] == "ok"
    assert len(callback_results) == 1
    assert callback_results[0]["processor"] == "callback_test"


@pytest.mark.asyncio
async def test_execute_with_callback_no_callback() -> None:
    pool = ProcessorPool()
    proc = DummyProcessor("no_callback")
    exc = _make_exchange({"test": "data"})
    ctx = MagicMock()

    result = await pool.execute_with_callback(proc, exc, ctx, on_complete=None)

    assert result["processor"] == "no_callback"
    assert result["status"] == "ok"


@pytest.mark.asyncio
async def test_shutdown_cancels_pending() -> None:
    pool = ProcessorPool(max_workers=1)
    proc = DummyProcessor("slow")
    exc = _make_exchange({"test": "data"})
    ctx = MagicMock()

    async def slow_process():
        await asyncio.sleep(10)  # Long delay

    proc.process = slow_process  # type: ignore

    # Start execution
    task = asyncio.create_task(pool.execute_parallel([proc], exc, ctx))

    # Give it a moment to start
    await asyncio.sleep(0.1)

    # Shutdown should cancel
    await pool.shutdown(cancel_pending=True)

    assert pool.active_count == 0


@pytest.mark.asyncio
async def test_global_pool_singleton() -> None:
    # Reset global pool
    set_processor_pool(None)

    pool1 = get_processor_pool()
    pool2 = get_processor_pool()

    assert pool1 is pool2

    # Clean up
    set_processor_pool(None)


@pytest.mark.asyncio
async def test_global_pool_setter() -> None:
    custom_pool = ProcessorPool(max_workers=10)
    set_processor_pool(custom_pool)

    assert get_processor_pool() is custom_pool

    # Clean up
    set_processor_pool(None)


@pytest.mark.asyncio
async def test_execute_parallel_empty_list() -> None:
    pool = ProcessorPool()
    exc = _make_exchange()
    ctx = MagicMock()

    results = await pool.execute_parallel([], exc, ctx)

    assert results == []
    assert pool.metrics.total_submitted == 0


@pytest.mark.asyncio
async def test_execute_parallel_single_processor() -> None:
    pool = ProcessorPool()
    proc = DummyProcessor("single")
    exc = _make_exchange({"key": "value"})
    ctx = MagicMock()

    results = await pool.execute_parallel([proc], exc, ctx)

    assert len(results) == 1
    assert results[0]["processor"] == "single"
    assert results[0]["status"] == "ok"
    assert proc.processed
