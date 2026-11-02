"""pg_runner internals package (S55 W3 decomp from pg_runner_internals.py 618 LOC).

4 classes + 2 helpers decomposed в 4 files:
- ``rows.py``: WorkflowEventRow, WorkflowInstanceRow (Pydantic-like rows)
- ``state.py``: WorkflowState (state machine, 5 methods)
- ``event_store.py``: WorkflowEventStore + _find_last_snapshot, _advisory_lock_key
- ``instance_store.py``: WorkflowInstanceStore
- ``workflow_dlq.py``: DLQ-контракт исчерпанных шагов (ADR-0408)
- ``step_audit.py``: модель аудита шагов workflow (ADR-0414)

Backward-compat: ``from src.backend.infrastructure.workflow.pg_runner_internals import WorkflowState`` works.
"""

from __future__ import annotations

from src.backend.infrastructure.workflow.pg_runner_internals.event_store import (
    WorkflowEventStore,  # S55 W3: re-export
    _advisory_lock_key,  # S55 W3: re-export
    _find_last_snapshot,  # S55 W3: re-export
)
from src.backend.infrastructure.workflow.pg_runner_internals.instance_store import (
    WorkflowInstanceStore,  # S55 W3: re-export
)
from src.backend.infrastructure.workflow.pg_runner_internals.rows import (
    WorkflowEventRow,  # S55 W3: re-export
    WorkflowInstanceRow,  # S55 W3: re-export
)
from src.backend.infrastructure.workflow.pg_runner_internals.state import (
    WorkflowState,  # S55 W3: re-export
)
from src.backend.infrastructure.workflow.pg_runner_internals.step_audit import (
    AUDIT_CAPABILITY,  # ADR-0414: re-export
    PHASE_CANCELLED,
    PHASE_FAILED,
    PHASE_STARTED,
    PHASE_SUCCEEDED,
    emit_step_audit,
    step_audit_enabled,
    step_start_logged,
    step_terminal_logged,
)
from src.backend.infrastructure.workflow.pg_runner_internals.workflow_dlq import (
    WORKFLOW_DLQ_TRANSPORT,  # ADR-0408: re-export
    WorkflowDLQPublisher,  # ADR-0408: re-export
    build_exhausted_step_envelope,  # ADR-0408: re-export
)

__all__ = (
    "AUDIT_CAPABILITY",
    "PHASE_CANCELLED",
    "PHASE_FAILED",
    "PHASE_STARTED",
    "PHASE_SUCCEEDED",
    "WORKFLOW_DLQ_TRANSPORT",
    "WorkflowDLQPublisher",
    "WorkflowEventRow",
    "WorkflowEventStore",
    "WorkflowInstanceRow",
    "WorkflowInstanceStore",
    "WorkflowState",
    "_advisory_lock_key",
    "_find_last_snapshot",
    "build_exhausted_step_envelope",
    "emit_step_audit",
    "step_audit_enabled",
    "step_start_logged",
    "step_terminal_logged",
)
