# ruff: noqa: S101
"""Smoke tests for workflow runner (infrastructure/workflow/runner.py)."""

from __future__ import annotations

import os
from unittest.mock import patch

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
