"""ADR-045 — workflow primitives ядра (Wave C scaffold).

Public API подпакета. Использовать как
``from src.backend.core.workflow import WorkflowBackend, WorkflowHandle``.

Wave C поставляет только Protocol + Pydantic-модели + in-memory Fake.
Конкретные impl'ы (`TemporalWorkflowBackend`, `PgRunnerWorkflowBackend`)
— Wave D, в `infrastructure/workflow/`.
"""

from typing import Any

from src.backend.core.workflow.backend import (
    WorkflowBackend,
    WorkflowHandle,
    WorkflowResult,
    WorkflowStatus,
)
from src.backend.core.workflow.fake_backend import FakeWorkflowBackend


def __getattr__(name: str) -> Any:
    """Lazy re-export create_workflow_backend из infrastructure (ponytail)."""
    if name == "create_workflow_backend":
        from src.backend.infrastructure.workflow.factory import (
            create_workflow_backend,
        )

        return create_workflow_backend
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = (
    "FakeWorkflowBackend",
    "WorkflowBackend",
    "WorkflowHandle",
    "WorkflowResult",
    "WorkflowStatus",
    "create_workflow_backend",
)
