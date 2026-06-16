"""Capability-checked facade для IO indexers (S124 W1 batch 2)."""

from __future__ import annotations

from src.backend.services.io.indexers import get_order_indexer  # noqa: F401

__all__ = ("get_order_indexer",)
