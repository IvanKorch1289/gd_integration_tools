"""Capability-checked facade для external API base client (S120 W1 + Sprint 225 lazy proxy).

ADR-0207: extensions/* используют ``BaseExternalAPIClient`` для HTTP-интеграций
со внешними API (SKB, DaData, WebAutomation).

Sprint 225 refactor: convert direct re-export to ``__getattr__``-based lazy
proxy. Устраняет layer-violation ``core → services`` — services
импортируются только при lookup атрибута.
"""

from __future__ import annotations as annotations

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
