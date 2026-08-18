"""Capability-checked facade для AD directory client (S124 W1 + Sprint 225 lazy proxy).

Sprint 225 refactor: convert direct re-export to ``__getattr__``-based lazy
proxy. Устраняет layer-violation ``core → services``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.backend.services.auth.ad_directory_client import (
        AdAuthError,
        AdSearchEntry,
    )

__all__ = ("AdAuthError", "AdSearchEntry")


def __getattr__(name: str) -> Any:
    """Lazy proxy: импорт services только при lookup атрибута."""
    if name in {"AdAuthError", "AdSearchEntry"}:
        from src.backend.services.auth import ad_directory_client as _m

        return getattr(_m, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
