"""D-AUDIT-FIX-184-1 regression test — CompensatingDriverWorker.

Closes BOTH Data P0 (D-AUDIT-NEW-1) + Workflow P0 (D-AUDIT-NEW-2).
Per D-SWARM-1: ``saga_state.py:239 list_compensating()`` had ZERO callers
before this worker. Now has 1.

Strict-test policy per D-LESSON-11: NO lax `with x: pass`.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from src.backend.infrastructure.workflow.compensating_driver import (
    CompensatingDriverWorker,
)


def _make_saga(tenant_id: str = "t-default") -> MagicMock:
    """Build a MagicMock WorkflowState for testing (avoids SQLAlchemy instance-state issues)."""
    s = MagicMock()
    s.workflow_id = uuid4()
    s.run_id = "test-run-1"
    s.tenant_id = tenant_id
    s.state = "compensating"
    return s


class _FakeRepo:
    """Fake WorkflowStateRepository that tracks calls."""

    def __init__(self, stuck: list[MagicMock]) -> None:
        self._stuck = stuck
        self.list_calls = 0
        self.signal_calls: list[tuple] = []

    async def list_compensating(self, *, tenant_id=None, limit=100) -> list:
        self.list_calls += 1
        return list(self._stuck)

    async def signal_event(self, workflow_id, run_id, *, event):
        self.signal_calls.append((workflow_id, run_id, event))
        return MagicMock(state=event)


@asynccontextmanager
async def _fake_session():
    """Fake async session context manager (no real DB connection)."""
    session = MagicMock()
    yield session


def _make_session_factory() -> MagicMock:
    """Returns a fake session_factory that yields the same session."""
    factory = MagicMock()
    factory.__class__.__module__ = "fake"  # prevent assertion mistake
    factory.return_value.__aenter__ = AsyncMock(side_effect=_fake_session_factory)
    factory.return_value.__aexit__ = AsyncMock(return_value=False)
    return factory


def _fake_session_factory():
    """Default async context manager."""
    return _fake_session()


def _make_session_factory_alt() -> MagicMock:
    """Returns a session_factory that uses _fake_session."""
    factory = MagicMock()
    cm = MagicMock()

    @asynccontextmanager
    async def _cm_inner():
        s = MagicMock()
        yield s

    cm.__aenter__ = AsyncMock(side_effect=lambda: _cm_inner().__aenter__())
    cm.__aexit__ = AsyncMock(return_value=False)
    factory.return_value = cm
    return factory


@pytest.mark.asyncio
async def test_scan_once_calls_list_compensating() -> None:
    """``_scan_once`` вызывает ``list_compensating`` через repo."""
    saga = _make_saga()
    fake_repo = _FakeRepo([saga])

    with patch(
        "src.backend.infrastructure.workflow.saga_state.WorkflowStateRepository",
    ) as MockRepo:
        MockRepo.return_value = fake_repo
        worker = CompensatingDriverWorker(
            session_factory=_make_session_factory_alt(),
        )
        await worker._scan_once()
        assert fake_repo.list_calls == 1


@pytest.mark.asyncio
async def test_scan_once_signals_rolled_back_for_each_stuck_saga() -> None:
    """Каждый stuck saga → signal_event(state='rolled_back')."""
    saga1 = _make_saga(tenant_id="t-1")
    saga2 = _make_saga(tenant_id="t-2")
    fake_repo = _FakeRepo([saga1, saga2])

    with patch(
        "src.backend.infrastructure.workflow.saga_state.WorkflowStateRepository",
    ) as MockRepo:
        MockRepo.return_value = fake_repo
        worker = CompensatingDriverWorker(
            session_factory=_make_session_factory_alt(),
        )
        await worker._scan_once()
        assert len(fake_repo.signal_calls) == 2
        # Both should be rolled_back
        for call in fake_repo.signal_calls:
            _workflow_id, _run_id, event = call
            assert event == "rolled_back"


@pytest.mark.asyncio
async def test_scan_once_no_stuck_sagas_is_noop() -> None:
    """Если list_compensating пуст — signal_event не вызывается."""
    fake_repo = _FakeRepo([])

    with patch(
        "src.backend.infrastructure.workflow.saga_state.WorkflowStateRepository",
    ) as MockRepo:
        MockRepo.return_value = fake_repo
        worker = CompensatingDriverWorker(
            session_factory=_make_session_factory_alt(),
        )
        await worker._scan_once()
        assert fake_repo.list_calls == 1
        assert fake_repo.signal_calls == []


@pytest.mark.asyncio
async def test_scan_once_handles_per_saga_exception() -> None:
    """Если signal_event fails на одной saga — продолжаем другие.

    DLQ-pattern: per-saga exception НЕ останавливает scan loop.
    """
    saga1 = _make_saga()
    saga2 = _make_saga()
    fake_repo = _FakeRepo([saga1, saga2])

    # saga1 fail, saga2 success
    async def signal_event_sometimes(workflow_id, run_id, *, event):
        if workflow_id == saga1.workflow_id:
            raise RuntimeError("simulated per-saga failure")
        fake_repo.signal_calls.append((workflow_id, run_id, event))
        return MagicMock()

    fake_repo.signal_event = signal_event_sometimes

    with patch(
        "src.backend.infrastructure.workflow.saga_state.WorkflowStateRepository",
    ) as MockRepo:
        MockRepo.return_value = fake_repo
        worker = CompensatingDriverWorker(
            session_factory=_make_session_factory_alt(),
        )
        # Should NOT raise
        await worker._scan_once()
        # saga2 should have been called
        assert any(call[0] == saga2.workflow_id for call in fake_repo.signal_calls)


@pytest.mark.asyncio
async def test_start_and_stop_lifecycle() -> None:
    """start() spawns task, stop() cancels it cleanly."""
    fake_repo = _FakeRepo([])

    with patch(
        "src.backend.infrastructure.workflow.saga_state.WorkflowStateRepository",
    ) as MockRepo:
        MockRepo.return_value = fake_repo
        worker = CompensatingDriverWorker(
            session_factory=_make_session_factory_alt(),
            interval_seconds=0.1,  # fast tick for test
        )
        await worker.start()
        assert worker._task is not None
        # Let one tick run
        await asyncio.sleep(0.2)
        await worker.stop()
        assert worker._task is None


@pytest.mark.asyncio
async def test_start_idempotent() -> None:
    """Calling start() twice does not spawn duplicate tasks."""
    worker = CompensatingDriverWorker(
        session_factory=_make_session_factory_alt(),
        interval_seconds=0.1,
    )
    await worker.start()
    first_task = worker._task
    await worker.start()  # should be no-op
    assert worker._task is first_task
    await worker.stop()
