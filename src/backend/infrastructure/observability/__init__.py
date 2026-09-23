"""Observability package (G3): correlation, metrics, tracing, PII filter."""

from src.backend.infrastructure.observability.correlation import (  # noqa: F401 — re-export
    get_correlation_id,
    new_correlation_id,
    set_correlation_context,
)
from src.backend.infrastructure.observability.pii_filter import redact_for_observability

__all__ = (
    "get_correlation_id",
    "new_correlation_id",
    "redact_for_observability",
    "set_correlation_context",
)
