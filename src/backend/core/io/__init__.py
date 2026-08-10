"""Capability-checked facade для IO indexers (S124 W1 batch 2)."""

from __future__ import annotations as annotations

from src.backend.services.io.indexers import get_order_indexer  # noqa: F401 — re-export as get_order_indexer  # noqa: F401 — re-export

__all__ = ("get_order_indexer",)
