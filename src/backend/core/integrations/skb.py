"""Capability-checked facade для SKB API service (S124 W1 + Sprint 225 lazy proxy).

Sprint 225 refactor: convert direct re-export to ``__getattr__``-based lazy
proxy. Устраняет layer-violation ``core → services``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.backend.services.integrations.skb import (
        APISKBService,
        get_skb_service,
    )

__all__ = ("APISKBService", "get_skb_service")


def __getattr__(name: str) -> Any:
    """Lazy proxy: импорт services только при lookup атрибута."""
    if name in {"APISKBService", "get_skb_service"}:
        from src.backend.services.integrations import skb as _m

        return getattr(_m, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
