"""ADR-045 — workflow primitives ядра (Wave C scaffold).

Public API подпакета. Использовать как
``from src.backend.core.workflow import WorkflowBackend, WorkflowHandle``.

Wave C поставляет только Protocol + Pydantic-модели + in-memory Fake.
Конкретные impl'ы (`TemporalWorkflowBackend`, `PgRunnerWorkflowBackend`)
— Wave D, в `infrastructure/workflow/`.
"""

from src.backend.core.workflow.backend import (
    WorkflowBackend,
    WorkflowHandle,
    WorkflowResult,
    WorkflowStatus,
)
from src.backend.core.workflow.fake_backend import FakeWorkflowBackend

__all__ = (
    "FakeWorkflowBackend",
    "WorkflowBackend",
    "WorkflowHandle",
    "WorkflowResult",
    "WorkflowStatus",
)
