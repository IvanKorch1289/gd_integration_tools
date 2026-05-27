"""Backward-compat shim для OrderService (Sprint 7, R-V15-16)."""

from __future__ import annotations

import warnings

from extensions.core_entities.orders.services.orders import (
    OrderService,
    get_order_service,
)

__all__ = ("OrderService", "get_order_service")

warnings.warn(
    "src.backend.services.core.orders устарел; используйте "
    "extensions.core_entities.orders.services.orders (R-V15-16).",
    DeprecationWarning,
    stacklevel=2,
)
