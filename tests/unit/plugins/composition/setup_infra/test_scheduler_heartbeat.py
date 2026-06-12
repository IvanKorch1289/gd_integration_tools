"""S71 W3 — TD-S64-W2 closure tests for scheduler leader lock auto-extend."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest


@pytest.mark.asyncio
async def test_heartbeat_extends_lock(monkeypatch: pytest.MonkeyPatch) -> None:
    """Heartbeat loop should extend lock every TTL/5 seconds."""
    from src.backend.plugins.composition.setup_infra import scheduler_leader

    # Setup: lock handle exists, extend returns True
    fake_lock = AsyncMock()
    fake_lock.extend = AsyncMock(return_value=True)
    monkeypatch.setattr(scheduler_leader, "_scheduler_lock_handle", fake_lock)
    monkeypatch.setattr(scheduler_leader, "_SCHEDULER_LEADER_HEARTBEAT_S", 0.01)

    # Run 3 iterations then cancel
    task = asyncio.create_task(scheduler_leader._scheduler_heartbeat_loop())
    await asyncio.sleep(0.05)  # ~5 iterations
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert fake_lock.extend.await_count >= 1, "extend was never called"
    for call in fake_lock.extend.call_args_list:
        assert call.kwargs.get("additional_seconds") == 300


@pytest.mark.asyncio
async def test_heartbeat_stops_when_extend_returns_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If extend returns False (lock lost) → loop exits, leader status cleared."""
    from src.backend.plugins.composition.setup_infra import scheduler_leader

    fake_lock = AsyncMock()
    fake_lock.extend = AsyncMock(return_value=False)
    monkeypatch.setattr(scheduler_leader, "_scheduler_lock_handle", fake_lock)
    monkeypatch.setattr(scheduler_leader, "_SCHEDULER_LEADER_HEARTBEAT_S", 0.01)
    monkeypatch.setattr(scheduler_leader, "_scheduler_leader_acquired", True)

    await scheduler_leader._scheduler_heartbeat_loop()

    assert scheduler_leader._scheduler_leader_acquired is False
    assert fake_lock.extend.await_count == 1


@pytest.mark.asyncio
async def test_heartbeat_retries_on_transient_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Network blip → log + continue (next iteration)."""
    from src.backend.plugins.composition.setup_infra import scheduler_leader

    fake_lock = AsyncMock()
    fake_lock.extend = AsyncMock(side_effect=[ConnectionError("redis blip"), True])
    monkeypatch.setattr(scheduler_leader, "_scheduler_lock_handle", fake_lock)
    monkeypatch.setattr(scheduler_leader, "_SCHEDULER_LEADER_HEARTBEAT_S", 0.01)

    task = asyncio.create_task(scheduler_leader._scheduler_heartbeat_loop())
    await asyncio.sleep(0.05)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert fake_lock.extend.await_count >= 2
