"""Core audit facade — lazy re-exports (ponytail: thin proxy).

Entry points and services must import ``get_audit_log`` from here,
not from ``infrastructure.audit.event_log`` directly.
"""

from __future__ import annotations

from typing import Any

__all__ = ("get_audit_log",)


def __getattr__(name: str) -> Any:
    if name == "get_audit_log":
        from src.backend.infrastructure.audit.event_log import get_audit_log

        return get_audit_log
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
