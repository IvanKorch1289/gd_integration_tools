"""DEPRECATED: re-export shim (S168 W13 P2-7).

Moved to src.backend.infrastructure.workflow.outbox_worker.
Will be removed в S169+.
"""
import warnings
from src.backend.infrastructure.workflow.outbox_worker import (  # noqa: F401
    _publish,
    start_outbox_worker,
    stop_outbox_worker,
)

warnings.warn(
    "src.backend.workflows.outbox_worker is deprecated (S168 W13 P2-7), "
    "use src.backend.infrastructure.workflow.outbox_worker instead. "
    "Will be removed в S169+.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = ("_publish", "start_outbox_worker", "stop_outbox_worker")
