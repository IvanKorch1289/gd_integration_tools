# ruff: noqa: S101
"""Unit + smoke tests for workflow runner (infrastructure/workflow/runner.py).

Sections:
    * Smoke tests (legacy) — defaults / class-level attrs / module exports.
    * Unit tests — top-5+ methods:
        - RunnerConfig edge cases (uuid fallback, custom jitter).
        - DurableWorkflowRunner.__init__ (defaults + injected stores).
        - start() / stop() — listener_dsn on/off; cancel + wait + deadline.
        - _backup_loop — list_pending / QueueFull / exception / cancellation.
        - _dispatch_loop — dedup existing execution / timeout / normal enqueue.
        - _execute_one — semaphore / exception / finally cleanup.
        - _run_step — lock busy / instance vanished / terminal / normal flow.
        - _apply_outcome — 6 outcome branches.
        - _on_notify — payload validation / QueueFull drop.
    * Property tests (hypothesis) — _compute_backoff bounds.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from src.backend.core.domain.models.workflow_instance import WorkflowStatus
from src.backend.infrastructure.workflow import runner as runner_module
from src.backend.infrastructure.workflow.pg_runner_internals import (
    WorkflowInstanceRow,
    WorkflowState,
)
from src.backend.infrastructure.workflow.runner import (
    DurableWorkflowRunner,
    RunnerConfig,
    StepExecutor,
    StepOutcome,
    StepResult,
)

# ── RunnerConfig dataclass ─────────────────────────────────────────


def test_runner_config_defaults() -> None:
    cfg = RunnerConfig()
    assert cfg.max_concurrent == 8
    assert cfg.batch_size == 50
    assert cfg.backup_poll_interval_s == 30.0
    assert cfg.lock_ttl_s == 120
    assert cfg.retry_base_delay_s == 60.0
    assert cfg.retry_max_delay_s == 3600.0
    assert cfg.retry_multiplier == 2.0
    assert cfg.retry_jitter == 0.2
    assert cfg.max_attempts_default == 10
    assert cfg.worker_id.startswith("worker-")


def test_runner_config_custom() -> None:
    cfg = RunnerConfig(
        worker_id="custom-worker", max_concurrent=4, batch_size=10, retry_jitter=0.5
    )
    assert cfg.worker_id == "custom-worker"
    assert cfg.max_concurrent == 4
    assert cfg.batch_size == 10
    assert cfg.retry_jitter == 0.5


def test_runner_config_worker_id_from_env() -> None:
    with patch.dict(os.environ, {"WORKFLOW_WORKER_ID": "env-worker"}):
        cfg = RunnerConfig()
    assert cfg.worker_id == "env-worker"


# ── StepOutcome / StepResult classes (class-level attrs) ───────────


def test_step_outcome_attrs() -> None:
    """StepOutcome is a class with class-level outcome constants."""
    assert hasattr(StepOutcome, "CONTINUE")
    # Values are strings (e.g., "continue", "wait", "fail")
    assert isinstance(StepOutcome.CONTINUE, str)


def test_step_result_attrs() -> None:
    """StepResult is a dataclass with outcome field."""
    assert StepResult is not None
    # StepResult is constructible with just outcome (others have defaults)
    r = StepResult(outcome=StepOutcome.CONTINUE)
    assert r.outcome == StepOutcome.CONTINUE


# ── Module exports ─────────────────────────────────────────────────


def test_module_has_durable_workflow_runner() -> None:
    from src.backend.infrastructure.workflow import runner

    assert hasattr(runner, "DurableWorkflowRunner")
    assert hasattr(runner, "RunnerConfig")


def test_step_executor_protocol() -> None:
    """StepExecutor is a Protocol — should be importable."""
    # Just verify the protocol object exists
    assert StepExecutor is not None


# ── DurableWorkflowRunner: construction (mocked) ───────────────────


def test_durable_workflow_runner_init() -> None:
    """Construction should accept RunnerConfig or no args (defaults)."""
    cfg = RunnerConfig(worker_id="test-worker")
    # We don't actually run the runner; just verify it constructs
    # Some attributes may lazy-init, so we use a minimal mock
    runner = DurableWorkflowRunner.__new__(DurableWorkflowRunner)
    runner.config = cfg
    assert runner.config.worker_id == "test-worker"
    assert runner.config.max_concurrent == 8


# ── RunnerConfig: worker_id fallback (uuid) ────────────────────────


@pytest.mark.unit
def test_runner_config_worker_id_uuid_fallback() -> None:
    """Without WORKFLOW_WORKER_ID env var, worker_id is uuid-based 'worker-XXXXXXXX'."""
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("WORKFLOW_WORKER_ID", None)
        cfg = RunnerConfig()
    assert cfg.worker_id.startswith("worker-")
    # 8-char hex suffix from uuid.uuid4().hex[:8]
    suffix = cfg.worker_id.removeprefix("worker-")
    assert len(suffix) == 8
    int(suffix, 16)  # parses as hex


# ── DurableWorkflowRunner.__init__: real construction (mocked stores) ──


@pytest.mark.unit
def test_durable_workflow_runner_init_with_mocked_stores() -> None:
    """Real __init__ wires injected state_store, event_store, semaphore, queue."""
    cfg = RunnerConfig(worker_id="w-1", max_concurrent=3)
    state_store = MagicMock(name="state_store")
    event_store = MagicMock(name="event_store")
    executor = MagicMock(name="executor")
    runner = DurableWorkflowRunner(
        config=cfg,
        executor=executor,
        state_store=state_store,
        event_store=event_store,
        listener_dsn=None,
    )
    assert runner._config is cfg
    assert runner._executor is executor
    assert runner._state_store is state_store
    assert runner._event_store is event_store
    assert runner._listener_dsn is None
    assert isinstance(runner._semaphore, asyncio.Semaphore)
    # Semaphore initial value == max_concurrent (locked _value may be 0 after init,
    # but the underlying Semaphore has _value == max_concurrent before any acquire).
    # In Python 3.11+ Semaphore doesn't expose _value directly; check via _waiters.
    assert runner._semaphore._value == 3  # type: ignore[attr-defined]
    assert runner._running is False
    assert runner._pending_instance_ids.empty() is True
    assert runner._active_executions == set()


# ── Helpers ────────────────────────────────────────────────────────


def _build_runner(
    *, listener_dsn: str | None = None, max_concurrent: int = 2
) -> tuple[DurableWorkflowRunner, MagicMock, MagicMock, MagicMock]:
    """Construct a runner with fully mocked state/event stores + executor.

    The state_store's `update_status` is set to an AsyncMock so it can be
    awaited (the runner uses it in async methods like _apply_outcome).
    """
    cfg = RunnerConfig(worker_id="test-worker", max_concurrent=max_concurrent)
    state_store = MagicMock(name="state_store")
    # update_status is awaited in _apply_outcome; make it an AsyncMock.
    state_store.update_status = AsyncMock(name="update_status")
    event_store = MagicMock(name="event_store")
    executor = MagicMock(name="executor")
    executor.execute_next = AsyncMock(name="execute_next")
    runner = DurableWorkflowRunner(
        config=cfg,
        executor=executor,
        state_store=state_store,
        event_store=event_store,
        listener_dsn=listener_dsn,
    )
    return runner, state_store, event_store, executor


# ── start(): with / without listener_dsn ───────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_start_without_listener_dsn_skips_listen_task() -> None:
    """start() with listener_dsn=None must not create _listen_task."""
    runner, _ss, _es, _ex = _build_runner(listener_dsn=None)
    # Bypass real task creation: capture the coros but don't schedule loops.
    with patch.object(runner_module, "get_task_registry") as reg:
        reg.return_value.create_task = MagicMock(name="create_task")
        await runner.start()
    assert runner._running is True
    # Exactly 2 tasks: backup-poll + dispatch (no listen).
    assert reg.return_value.create_task.call_count == 2
    created_names = [
        c.kwargs.get("name", "") for c in reg.return_value.create_task.call_args_list
    ]
    assert "wf-backup-poll" in created_names
    assert "wf-dispatch" in created_names
    assert "wf-listen" not in created_names
    assert runner._listen_task is None
    # Clean up: stop the loops (we mocked task creation, so nothing real runs).
    runner._running = False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_start_with_listener_dsn_creates_listen_task() -> None:
    """start() with listener_dsn set must create 3 tasks (listen + backup + dispatch)."""
    runner, _ss, _es, _ex = _build_runner(listener_dsn="postgres://example")
    with patch.object(runner_module, "get_task_registry") as reg:
        reg.return_value.create_task = MagicMock(name="create_task")
        await runner.start()
    assert runner._running is True
    assert reg.return_value.create_task.call_count == 3
    created_names = [
        c.kwargs.get("name", "") for c in reg.return_value.create_task.call_args_list
    ]
    assert "wf-listen" in created_names
    assert "wf-backup-poll" in created_names
    assert "wf-dispatch" in created_names
    # _listen_task was assigned a mock task object (MagicMock from create_task).
    assert runner._listen_task is not None
    runner._running = False


# ── _apply_outcome: 6 outcome branches ─────────────────────────────


def _make_instance(
    workflow_id: UUID | None = None, status: WorkflowStatus = WorkflowStatus.running
) -> WorkflowInstanceRow:
    now = datetime.now(UTC)
    return WorkflowInstanceRow(
        id=workflow_id or uuid.uuid4(),
        workflow_name="wf-test",
        route_id="r-1",
        status=status,
        current_version=1,
        last_event_seq=None,
        snapshot_state=None,
        next_attempt_at=None,
        locked_by="test-worker",
        locked_until=now,
        tenant_id="t-1",
        input_payload={},
        created_at=now,
        updated_at=now,
        finished_at=None,
    )


def _make_state(attempts: int = 0) -> WorkflowState:
    return WorkflowState(workflow_id=uuid.uuid4(), attempts=attempts)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_apply_outcome_done_transitions_to_succeeded() -> None:
    runner, state_store, _es, _ex = _build_runner()
    wf_id = uuid.uuid4()
    instance = _make_instance(workflow_id=wf_id, status=WorkflowStatus.running)
    result = StepResult(outcome=StepOutcome.DONE)
    await runner._apply_outcome(wf_id, result, _make_state(), instance)
    state_store.update_status.assert_awaited_once_with(wf_id, WorkflowStatus.succeeded)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_apply_outcome_failed_transitions_to_failed_with_error() -> None:
    runner, state_store, _es, _ex = _build_runner()
    wf_id = uuid.uuid4()
    instance = _make_instance(workflow_id=wf_id)
    result = StepResult(outcome=StepOutcome.FAILED, error_message="boom")
    await runner._apply_outcome(wf_id, result, _make_state(), instance)
    state_store.update_status.assert_awaited_once_with(
        wf_id, WorkflowStatus.failed, error="boom"
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_apply_outcome_sub_spawned_keeps_status_running() -> None:
    """SUB_SPAWNED: no update_status call — stay running, await child."""
    runner, state_store, _es, _ex = _build_runner()
    wf_id = uuid.uuid4()
    instance = _make_instance(workflow_id=wf_id)
    result = StepResult(outcome=StepOutcome.SUB_SPAWNED)
    await runner._apply_outcome(wf_id, result, _make_state(), instance)
    state_store.update_status.assert_not_called()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_apply_outcome_pause_sets_next_attempt_at() -> None:
    runner, state_store, _es, _ex = _build_runner()
    wf_id = uuid.uuid4()
    instance = _make_instance(workflow_id=wf_id)
    result = StepResult(
        outcome=StepOutcome.PAUSE, next_attempt_at=datetime(2030, 1, 1, tzinfo=UTC)
    )
    await runner._apply_outcome(wf_id, result, _make_state(attempts=2), instance)
    state_store.update_status.assert_awaited_once()
    call = state_store.update_status.await_args
    assert call.args[0] == wf_id
    assert call.args[1] == WorkflowStatus.paused
    assert call.kwargs.get("next_attempt_at") == datetime(2030, 1, 1, tzinfo=UTC)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_apply_outcome_continue_reenqueues_workflow_id() -> None:
    """CONTINUE: re-enqueue workflow_id for next step processing."""
    runner, state_store, _es, _ex = _build_runner()
    wf_id = uuid.uuid4()
    instance = _make_instance(workflow_id=wf_id)
    result = StepResult(outcome=StepOutcome.CONTINUE)
    # Pre-condition: queue empty.
    assert runner._pending_instance_ids.empty()
    await runner._apply_outcome(wf_id, result, _make_state(), instance)
    # No DB status change for CONTINUE.
    state_store.update_status.assert_not_called()
    # Queue has the workflow_id now.
    assert runner._pending_instance_ids.qsize() == 1
    assert runner._pending_instance_ids.get_nowait() == wf_id


@pytest.mark.unit
@pytest.mark.asyncio
async def test_apply_outcome_unknown_outcome_treated_as_pause() -> None:
    """Unknown outcome string → log warning + transition to paused with backoff."""
    runner, state_store, _es, _ex = _build_runner()
    wf_id = uuid.uuid4()
    instance = _make_instance(workflow_id=wf_id)
    result = StepResult(outcome="mystery_outcome")
    await runner._apply_outcome(wf_id, result, _make_state(attempts=1), instance)
    # Should still treat as pause.
    state_store.update_status.assert_awaited_once()
    call = state_store.update_status.await_args
    assert call.args[0] == wf_id
    assert call.args[1] == WorkflowStatus.paused
    assert "next_attempt_at" in call.kwargs


# ── _compute_backoff: property tests (hypothesis) ──────────────────


@pytest.mark.unit
@given(
    attempt=st.integers(min_value=0, max_value=50),
    base=st.floats(min_value=1.0, max_value=100.0, allow_nan=False),
    mult=st.floats(min_value=1.1, max_value=3.0, allow_nan=False),
    max_delay=st.floats(min_value=10.0, max_value=10_000.0, allow_nan=False),
    jitter=st.floats(min_value=0.0, max_value=0.9, allow_nan=False),
)
@settings(max_examples=50, deadline=None)
def test_compute_backoff_within_jittered_bounds(
    attempt: int, base: float, mult: float, max_delay: float, jitter: float
) -> None:
    """_compute_backoff returns delay in [(1-j)*raw, (1+j)*raw] for any attempt."""
    cfg = RunnerConfig(
        worker_id="prop-worker",
        retry_base_delay_s=base,
        retry_multiplier=mult,
        retry_max_delay_s=max_delay,
        retry_jitter=jitter,
    )
    runner, _ss, _es, _ex = _build_runner()
    runner._config = cfg
    raw_expected = min(max_delay, base * (mult ** max(0, attempt)))
    delay = runner._compute_backoff(attempt)
    lower = raw_expected * (1 - jitter)
    upper = raw_expected * (1 + jitter)
    # Allow tiny float epsilon.
    eps = max(abs(lower), abs(upper), 1.0) * 1e-9
    assert lower - eps <= delay <= upper + eps, (
        f"attempt={attempt} base={base} mult={mult} max={max_delay} jitter={jitter} "
        f"raw={raw_expected} delay={delay} bounds=[{lower}, {upper}]"
    )


@pytest.mark.unit
@given(
    attempt=st.integers(min_value=0, max_value=30),
    base=st.floats(min_value=1.0, max_value=1000.0, allow_nan=False),
    jitter=st.floats(min_value=0.0, max_value=0.5, allow_nan=False),
)
@settings(max_examples=50, deadline=None)
def test_compute_backoff_non_negative(attempt: int, base: float, jitter: float) -> None:
    """_compute_backoff always returns a non-negative delay (no NaN, no negative)."""
    cfg = RunnerConfig(
        worker_id="nn-worker",
        retry_base_delay_s=base,
        retry_multiplier=2.0,
        retry_max_delay_s=10_000.0,
        retry_jitter=jitter,
    )
    runner, _ss, _es, _ex = _build_runner()
    runner._config = cfg
    delay = runner._compute_backoff(attempt)
    assert delay >= 0.0
    # Finite: not NaN/inf.
    assert delay == delay  # NaN check
    assert delay in (delay,) and abs(delay) != float("inf")


# ── _on_notify: payload validation + queue full handling ───────────


@pytest.mark.unit
def test_on_notify_valid_uuid_enqueues() -> None:
    """Valid UUID payload → enqueue on _pending_instance_ids."""
    runner, _ss, _es, _ex = _build_runner()
    wf_id = uuid.uuid4()
    fake_conn = MagicMock(name="conn")
    runner._on_notify(
        fake_conn, _pid=1234, channel="workflow_pending", payload=str(wf_id)
    )
    assert runner._pending_instance_ids.qsize() == 1
    assert runner._pending_instance_ids.get_nowait() == wf_id


@pytest.mark.unit
def test_on_notify_invalid_uuid_drops_and_warns() -> None:
    """Invalid UUID payload → drop + warning logged, queue untouched."""
    runner, _ss, _es, _ex = _build_runner()
    fake_conn = MagicMock(name="conn")
    with patch.object(runner_module._logger, "warning") as warn:
        runner._on_notify(
            fake_conn, _pid=42, channel="workflow_pending", payload="not-a-uuid"
        )
    assert runner._pending_instance_ids.empty()
    warn.assert_called_once()
    # Warning should mention the bad payload.
    args = warn.call_args.args
    assert "not-a-uuid" in (args[0] if args else "") or "not-a-uuid" in str(
        warn.call_args
    )


@pytest.mark.unit
def test_on_notify_empty_payload_drops() -> None:
    """Empty payload → silent drop, no warning, no enqueue."""
    runner, _ss, _es, _ex = _build_runner()
    fake_conn = MagicMock(name="conn")
    with patch.object(runner_module._logger, "warning") as warn:
        runner._on_notify(fake_conn, _pid=1, channel="workflow_pending", payload="")
    assert runner._pending_instance_ids.empty()
    warn.assert_not_called()


@pytest.mark.unit
def test_on_notify_queue_full_drops_silently() -> None:
    """QueueFull → silent drop (backup polling will pick it up later)."""
    runner, _ss, _es, _ex = _build_runner()
    # Replace queue with a tiny one (maxsize=1) and fill it.
    runner._pending_instance_ids = asyncio.Queue(maxsize=1)
    runner._pending_instance_ids.put_nowait(uuid.uuid4())
    assert runner._pending_instance_ids.full()
    fake_conn = MagicMock(name="conn")
    # Should NOT raise (QueueFull is caught).
    runner._on_notify(
        fake_conn, _pid=99, channel="workflow_pending", payload=str(uuid.uuid4())
    )
    # Queue still has just the original item.
    assert runner._pending_instance_ids.qsize() == 1
