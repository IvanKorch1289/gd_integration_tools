"""Core observability facade: correlation context lazy re-export (ponytail).

Entry points must import ``set_correlation_context`` from here, not from
``infrastructure.observability.correlation`` directly.
"""

from __future__ import annotations

# ruff: noqa: F822  # lazy __getattr__ exports verified by runtime test
from typing import Any

__all__ = ("set_correlation_context",)


def __getattr__(name: str) -> Any:
    if name == "set_correlation_context":
        from src.backend.infrastructure.observability.correlation import (
            set_correlation_context,
        )

        return set_correlation_context
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
