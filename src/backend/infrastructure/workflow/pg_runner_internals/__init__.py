"""pg_runner internals package (S55 W3 decomp from pg_runner_internals.py 618 LOC).

4 classes + 2 helpers decomposed в 4 files:
- ``rows.py``: WorkflowEventRow, WorkflowInstanceRow (Pydantic-like rows)
- ``state.py``: WorkflowState (state machine, 5 methods)
- ``event_store.py``: WorkflowEventStore + _find_last_snapshot, _advisory_lock_key
- ``instance_store.py``: WorkflowInstanceStore

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

__all__ = (
    "WorkflowEventRow",
    "WorkflowInstanceRow",
    "WorkflowState",
    "WorkflowEventStore",
    "WorkflowInstanceStore",
    "_find_last_snapshot",
    "_advisory_lock_key",
)
