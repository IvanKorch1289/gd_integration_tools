"""DEPRECATED: re-export shim (S168 W13 P2-7).

Moved to src.backend.infrastructure.workflow.worker_probes.
Will be removed в S169+.
"""
import warnings
from src.backend.infrastructure.workflow.worker_probes import (  # noqa: F401
    WorkerProbesServer,
)

warnings.warn(
    "src.backend.workflows.worker_probes is deprecated (S168 W13 P2-7), "
    "use src.backend.infrastructure.workflow.worker_probes instead. "
    "Will be removed в S169+.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = ("WorkerProbesServer",)
