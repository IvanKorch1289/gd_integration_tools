"""DEPRECATED: re-export shim (S168 W13 P2-7).

Moved to src.backend.infrastructure.workflow.registry.
Will be removed в S169+.
"""
import warnings
from src.backend.infrastructure.workflow.registry import (  # noqa: F401
    WorkflowDescriptor,
    workflow_registry,
)

warnings.warn(
    "src.backend.workflows.registry is deprecated (S168 W13 P2-7), "
    "use src.backend.infrastructure.workflow.registry instead. "
    "Will be removed в S169+.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = ("WorkflowDescriptor", "workflow_registry")
