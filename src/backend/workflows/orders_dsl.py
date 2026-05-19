"""Deprecation facade — orders_dsl переехал в extensions/ (Sprint 9 K5 W4)."""

from __future__ import annotations

import warnings

from extensions.core_entities.orders.workflows.orders_dsl import *  # noqa: F401,F403
from extensions.core_entities.orders.workflows.orders_dsl import (
    build_all_order_workflows,
)

warnings.warn(
    "src.backend.workflows.orders_dsl is deprecated. "
    "Import from extensions.core_entities.orders.workflows.orders_dsl.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = ("build_all_order_workflows",)
