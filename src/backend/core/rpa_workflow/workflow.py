"""RPA Workflow — state machine + checkpoints + HITL (Wave 3)."""

from __future__ import annotations

import enum
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

__all__ = (
    "Checkpoint",
    "RPAState",
    "RPAWorkflow",
    "WorkflowRun",
    "get_rpa_workflow",
)


class RPAState(str, enum.Enum):
    """RPA workflow state machine."""

    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"  # human takeover
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(slots=True)
class Checkpoint:
    """Snapshot состояния на момент step."""

    step_name: str
    state: RPAState
    timestamp: float = 0.0
    data: dict[str, Any] = field(default_factory=dict)
    screenshot_path: str | None = None


@dataclass(slots=True)
class WorkflowRun:
    """Один run workflow'а."""

    run_id: str
    workflow_id: str
    state: RPAState = RPAState.PENDING
    started_at: float = 0.0
    paused_at: float | None = None
    resumed_at: float | None = None
    completed_at: float | None = None
    checkpoints: list[Checkpoint] = field(default_factory=list)
    last_error: str | None = None
    pause_reason: str | None = None
    operator: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class RPAWorkflow:
    """Coordinator для RPA workflow runs."""

    def __init__(self) -> None:
        self._runs: dict[str, WorkflowRun] = {}

    async def start(
        self,
        *,
        workflow_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> WorkflowRun:
        """Start new workflow run."""
        import time

        run = WorkflowRun(
            run_id=str(uuid.uuid4()),
            workflow_id=workflow_id,
            state=RPAState.RUNNING,
            started_at=time.time(),
            metadata=metadata or {},
        )
        self._runs[run.run_id] = run
        return run

    async def run_step(
        self,
        run: WorkflowRun,
        step_name: str,
        step_fn: Any = None,
        *,
        screenshot_path: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> Checkpoint:
        """Execute a step + create checkpoint."""
        import time

        if run.state not in (RPAState.RUNNING, RPAState.PAUSED):
            raise RuntimeError(
                f"Cannot run step {step_name!r} in state {run.state}"
            )
        cp = Checkpoint(
            step_name=step_name,
            state=RPAState.RUNNING,
            timestamp=time.time(),
            data=data or {},
            screenshot_path=screenshot_path,
        )
        run.checkpoints.append(cp)
        return cp

    async def pause(
        self,
        run: WorkflowRun,
        *,
        reason: str,
        operator: str | None = None,
    ) -> None:
        """Pause workflow для human takeover."""
        import time
        if run.state != RPAState.RUNNING:
            raise RuntimeError(f"Cannot pause in state {run.state}")
        run.state = RPAState.PAUSED
        run.paused_at = time.time()
        run.pause_reason = reason
        run.operator = operator

    async def resume(
        self,
        run: WorkflowRun,
        *,
        operator: str | None = None,
    ) -> None:
        """Resume workflow после human action."""
        import time
        if run.state != RPAState.PAUSED:
            raise RuntimeError(f"Cannot resume in state {run.state}")
        run.state = RPAState.RUNNING
        run.resumed_at = time.time()
        if operator is not None:
            run.operator = operator

    async def complete(self, run: WorkflowRun) -> None:
        """Mark workflow as completed."""
        import time
        run.state = RPAState.COMPLETED
        run.completed_at = time.time()

    async def fail(self, run: WorkflowRun, error: str) -> None:
        """Mark workflow as failed (с evidence)."""
        import time
        run.state = RPAState.FAILED
        run.last_error = error
        run.completed_at = time.time()

    def get(self, run_id: str) -> WorkflowRun | None:
        return self._runs.get(run_id)

    def list_all(self) -> list[WorkflowRun]:
        return list(self._runs.values())

    def list_by_workflow(self, workflow_id: str) -> list[WorkflowRun]:
        return [r for r in self._runs.values() if r.workflow_id == workflow_id]

    def list_by_state(self, state: RPAState) -> list[WorkflowRun]:
        return [r for r in self._runs.values() if r.state == state]


_wf: RPAWorkflow | None = None


def get_rpa_workflow() -> RPAWorkflow:
    global _wf
    if _wf is None:
        _wf = RPAWorkflow()
    return _wf


def reset_rpa_workflow() -> None:
    global _wf
    _wf = None
