"""Capability-checked facade для BaseService (S120 W3 + Sprint 225 lazy proxy).

ADR-0207: extensions/* services импортируют ``BaseService``.

Sprint 225 refactor: convert direct re-export to ``__getattr__``-based lazy
proxy. Устраняет layer-violation ``core → services``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.backend.services.core.base import (
        BaseService,
        create_service_class,
        get_service_for_model,
    )

__all__ = ("BaseService", "create_service_class", "get_service_for_model")


def __getattr__(name: str) -> Any:
    """Lazy proxy: импорт services только при lookup атрибута."""
    if name in {"BaseService", "create_service_class", "get_service_for_model"}:
        from src.backend.services.core import base as _m

        return getattr(_m, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
