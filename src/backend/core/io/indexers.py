"""Capability-checked facade для IO indexers (S124 W1).

ADR-0207: extensions/core_entities/orders/services/orders.py импортирует
``get_order_indexer`` из ``services.io.indexers`` (sub-package).
"""

from __future__ import annotations

from src.backend.services.io.indexers import (  # noqa: F401
    get_order_indexer,
)

__all__ = ("get_order_indexer",)
