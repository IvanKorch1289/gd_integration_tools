"""Core messaging facade: StreamClient lazy re-export (ponytail: thin proxy).

Entry points must import ``get_stream_client`` from here, not from
``infrastructure.clients.messaging.stream`` directly.
"""

from __future__ import annotations

# ruff: noqa: F822  # lazy __getattr__ exports verified by runtime test
from typing import Any

__all__ = ("get_stream_client",)


def __getattr__(name: str) -> Any:
    if name == "get_stream_client":
        from src.backend.infrastructure.clients.messaging.stream import (
            get_stream_client,
        )

        return get_stream_client
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
