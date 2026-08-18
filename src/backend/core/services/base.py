"""Re-export BaseExternalAPIClient for capability-checked access (S120 W1 + Sprint 225 lazy proxy).

Sprint 225 refactor: convert direct re-export to ``__getattr__``-based lazy
proxy.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.backend.services.core.base_external_api import BaseExternalAPIClient

__all__ = ("BaseExternalAPIClient",)


def __getattr__(name: str) -> Any:
    """Lazy proxy: импорт services только при lookup атрибута."""
    if name == "BaseExternalAPIClient":
        from src.backend.services.core import base_external_api as _m

        return _m.BaseExternalAPIClient
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
