"""Backward-compat shim для circuit breaker.

Sprint 1 V16 Single-Entry (Step 3.2): canonical-реализация переехала в
``src.backend.core.resilience.breaker``. Этот модуль остаётся как тонкий
re-export для существующих callsite'ов; будет удалён в Step 3.3 после
миграции callsites.
"""

from __future__ import annotations

from typing import Any

from src.backend.core.resilience.breaker import (
    Breaker,
    BreakerRegistry,
    BreakerSpec,
    CircuitBreaker,
    CircuitOpen,
    get_breaker_registry,
)

__all__ = (
    "Breaker",
    "BreakerRegistry",
    "BreakerSpec",
    "CircuitBreaker",
    "CircuitOpen",
    "breaker_registry",
    "get_breaker_registry",
)


def __getattr__(name: str) -> Any:
    """Module-level lazy accessor для backward compat ``breaker_registry``."""
    if name == "breaker_registry":
        return get_breaker_registry()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
