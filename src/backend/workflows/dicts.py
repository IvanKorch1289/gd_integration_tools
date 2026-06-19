"""DEPRECATED: re-export shim (S168 W12 P2-7).

Moved to src.backend.schemas.processing_result. Will be removed в S169+.
"""
import warnings
from src.backend.schemas.processing_result import (  # noqa: F401
    ProcessingResult,
)

warnings.warn(
    "src.backend.workflows.dicts is deprecated (S168 W12 P2-7), "
    "use src.backend.schemas.processing_result instead. "
    "Will be removed в S169+.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = ("ProcessingResult",)
