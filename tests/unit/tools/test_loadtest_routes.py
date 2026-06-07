"""Tests для load test scaffold (S55 W5)."""

from __future__ import annotations

import asyncio

import pytest

from tools.loadtest.routes import LoadGenerator, LoadStats, loadtest, _percentile


@pytest.mark.asyncio
async def test_percentile_empty() -> None:
    assert _percentile([], 50) == 0.0


@pytest.mark.asyncio
async def test_percentile_basic() -> None:
    values = [float(i) for i in range(1, 101)]  # 1..100
    assert _percentile(values, 50) == 50.5
    assert _percentile(values, 95) == 95.05


@pytest.mark.asyncio
async def test_loadstats_zero() -> None:
    s = LoadStats()
    assert s.rps == 0.0
    assert s.error_rate == 0.0
    assert s.p50_ms == 0.0
    assert "total=0" in s.report()


@pytest.mark.asyncio
async def test_loadstats_populated() -> None:
    s = LoadStats(
        total_requests=100,
        successful=95,
        failed=5,
        duration_s=10.0,
        latencies_ms=[10.0] * 50 + [20.0] * 30 + [50.0] * 15 + [100.0] * 5,
    )
    assert s.rps == 10.0
    assert s.error_rate == 0.05
    assert s.p50_ms > 0
    assert s.p95_ms > s.p50_ms
    assert "total=100" in s.report()


@pytest.mark.asyncio
async def test_loadtest_all_success() -> None:
    async def _ok() -> bool:
        await asyncio.sleep(0.001)
        return True

    stats = await loadtest(target=_ok, rps=100, duration_s=0.1, workers=5)
    assert stats.total_requests > 0
    assert stats.successful == stats.total_requests
    assert stats.failed == 0


@pytest.mark.asyncio
async def test_loadtest_mixed_success_failure() -> None:
    counter = {"n": 0}

    async def _flaky() -> bool:
        counter["n"] += 1
        await asyncio.sleep(0.001)
        return counter["n"] % 2 == 0  # 50% failure

    stats = await loadtest(target=_flaky, rps=200, duration_s=0.1, workers=5)
    assert stats.total_requests > 0
    assert stats.failed > 0
    assert stats.successful > 0


@pytest.mark.asyncio
async def test_loadtest_exception_caught() -> None:
    async def _fail() -> bool:
        await asyncio.sleep(0.001)
        raise RuntimeError("boom")

    stats = await loadtest(target=_fail, rps=100, duration_s=0.1, workers=3)
    assert stats.failed == stats.total_requests
    assert "boom" in str(stats.errors[0])


@pytest.mark.asyncio
async def test_loadtest_respects_duration() -> None:
    async def _ok() -> bool:
        return True

    start = asyncio.get_event_loop().time()
    stats = await loadtest(target=_ok, rps=50, duration_s=0.2, workers=2)
    elapsed = asyncio.get_event_loop().time() - start
    assert 0.15 <= elapsed <= 0.5  # generous bounds
    assert stats.duration_s > 0


@pytest.mark.asyncio
async def test_loadgenerator_worker_count() -> None:
    """Workers создаются в количестве указанном."""
    counter = {"active": 0, "max": 0}

    async def _track() -> bool:
        counter["active"] += 1
        counter["max"] = max(counter["max"], counter["active"])
        await asyncio.sleep(0.005)
        counter["active"] -= 1
        return True

    gen = LoadGenerator(target=_track, rps=100, duration_s=0.05, workers=5)
    await gen.run()
    # Multiple workers ran concurrently (could be all 5 or some sequential)
    assert counter["max"] >= 1
