"""Unit-тесты TemporalWorkerScaler — Sprint 12 K2 W2."""

# ruff: noqa: S101

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.backend.core.scaling.auto_scaler import TemporalWorkerScaler


def _make_pool(initial_workers: int = 2) -> Any:
    pool = MagicMock()
    state = {"workers": initial_workers}
    pool.current_workers = MagicMock(side_effect=lambda: state["workers"])

    async def start_worker(**_: Any) -> None:
        state["workers"] += 1

    async def stop_worker(**_: Any) -> None:
        state["workers"] = max(0, state["workers"] - 1)

    pool.start_worker = start_worker
    pool.stop_worker = stop_worker
    pool.get_queue_depth = AsyncMock(return_value={"default": 0})
    pool._state = state
    return pool


@pytest.mark.asyncio
async def test_scale_up_on_high_depth() -> None:
    pool = _make_pool(initial_workers=2)
    pool.get_queue_depth = AsyncMock(return_value={"default": 50})
    scaler = TemporalWorkerScaler(
        worker_pool=pool, min_workers=2, max_workers=20, cooldown_seconds=0
    )
    result = await scaler.tick()
    assert result["action"] == "up"
    assert pool._state["workers"] == 5


@pytest.mark.asyncio
async def test_scale_down_on_idle() -> None:
    pool = _make_pool(initial_workers=10)
    pool.get_queue_depth = AsyncMock(return_value={"default": 5})
    scaler = TemporalWorkerScaler(
        worker_pool=pool, min_workers=2, max_workers=20, cooldown_seconds=0
    )
    result = await scaler.tick()
    assert result["action"] == "down"
    assert pool._state["workers"] == 2


@pytest.mark.asyncio
async def test_max_workers_cap_respected() -> None:
    pool = _make_pool(initial_workers=2)
    pool.get_queue_depth = AsyncMock(return_value={"default": 10000})
    scaler = TemporalWorkerScaler(
        worker_pool=pool, min_workers=2, max_workers=8, cooldown_seconds=0
    )
    await scaler.tick()
    assert pool._state["workers"] == 8


@pytest.mark.asyncio
async def test_cooldown_blocks_consecutive_scales() -> None:
    pool = _make_pool(initial_workers=2)
    queue_depths = [{"default": 50}, {"default": 100}]
    pool.get_queue_depth = AsyncMock(side_effect=queue_depths)
    scaler = TemporalWorkerScaler(
        worker_pool=pool, min_workers=2, max_workers=20, cooldown_seconds=10
    )
    r1 = await scaler.tick()
    r2 = await scaler.tick()
    assert r1["action"] == "up"
    assert r2["action"] == "cooldown"


@pytest.mark.asyncio
async def test_noop_when_at_desired() -> None:
    pool = _make_pool(initial_workers=5)
    pool.get_queue_depth = AsyncMock(return_value={"default": 50})
    scaler = TemporalWorkerScaler(
        worker_pool=pool,
        min_workers=2,
        max_workers=20,
        target_tasks_per_worker=10,
        cooldown_seconds=0,
    )
    result = await scaler.tick()
    assert result["action"] == "noop"


@pytest.mark.asyncio
async def test_get_queue_depth_failure_returns_skip() -> None:
    pool = _make_pool()
    pool.get_queue_depth = AsyncMock(side_effect=RuntimeError("temporal down"))
    scaler = TemporalWorkerScaler(worker_pool=pool, cooldown_seconds=0)
    result = await scaler.tick()
    assert result["action"] == "skip"
