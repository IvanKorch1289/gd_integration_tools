"""Deprecation facade — payments_saga переехал в extensions/ (Sprint 9 K5 W4)."""

from __future__ import annotations

import warnings

from extensions.credit_pipeline.workflows.payments_saga import *  # noqa: F401,F403
from extensions.credit_pipeline.workflows.payments_saga import (
    build_payments_saga_workflow,
)

warnings.warn(
    "src.backend.workflows.payments_saga is deprecated. "
    "Import from extensions.credit_pipeline.workflows.payments_saga.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = ("build_payments_saga_workflow",)
