"""Stub for saga processor (real implementation removed per cleanup commit).

This file is a placeholder to satisfy imports from control_flow/__init__.py
and test_saga_double_fault_chaos.py. The real saga processor should be
restored from HEAD~ or re-implemented per audit W5 plan.

TODO(S180): restore SagaProcessor implementation per ADR-NEW-XX.
"""

from __future__ import annotations

from typing import Any


def _serialize_sub(processors: Any) -> Any:
    """Serialize sub-processors (placeholder)."""
    return processors


def _emit_saga_audit(*args: Any, **kwargs: Any) -> None:
    """Placeholder — no-op."""
    pass


class SagaStep:
    """Stub SagaStep class — placeholder."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.args = args
        self.kwargs = kwargs


class SagaProcessor:
    """Stub SagaProcessor class — placeholder."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.args = args
        self.kwargs = kwargs
