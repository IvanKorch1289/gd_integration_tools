"""Core security facade: PII streaming lazy re-export (ponytail: thin proxy).

Entry points must import ``PiiStreamPolicy`` / ``stream_filter`` from here,
not from ``infrastructure.security.pii_streaming`` directly.
"""

from __future__ import annotations

from typing import Any

__all__ = ("PiiStreamPolicy", "stream_filter")


def __getattr__(name: str) -> Any:
    if name in ("PiiStreamPolicy", "stream_filter"):
        from src.backend.infrastructure.security import pii_streaming as _m

        return getattr(_m, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
