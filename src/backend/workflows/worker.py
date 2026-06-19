"""DEPRECATED: re-export shim (S168 W13 P2-7).

Moved to src.backend.infrastructure.workflow.worker.
Will be removed в S169+.
"""
import warnings
from src.backend.infrastructure.workflow import worker as _worker_module  # noqa: F401

warnings.warn(
    "src.backend.workflows.worker is deprecated (S168 W13 P2-7), "
    "use src.backend.infrastructure.workflow.worker instead. "
    "Will be removed в S169+.",
    DeprecationWarning,
    stacklevel=2,
)

# Module-level re-export: expose all public names from new location
__all__ = getattr(_worker_module, "__all__", ())