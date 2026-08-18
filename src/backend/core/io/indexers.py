"""Capability-checked facade для IO indexers (S124 W1 + Sprint 225 lazy proxy).

Sprint 225 refactor: convert direct re-export to ``__getattr__``-based lazy
proxy.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.backend.services.io.indexers import get_order_indexer

__all__ = ("get_order_indexer",)


def __getattr__(name: str) -> Any:
    """Lazy proxy: импорт services только при lookup атрибута."""
    if name == "get_order_indexer":
        from src.backend.services.io import indexers as _m

        return _m.get_order_indexer
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
