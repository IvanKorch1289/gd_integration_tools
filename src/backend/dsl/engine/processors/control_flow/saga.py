"""Stub for saga processor (real implementation removed per cleanup commit).

This file is a placeholder to satisfy imports from control_flow/__init__.py
and saga_lra.py. The real saga processor should be restored from HEAD~ or
re-implemented per audit W5 plan.

TODO(S180): restore SagaProcessor implementation per ADR-NEW-XX.
"""

from __future__ import annotations

from typing import Any, Awaitable


def _serialize_sub(processors: Any) -> Any:
    """Serialize sub-processors (placeholder)."""
    return processors


async def _emit_saga_audit(*args: Any, **kwargs: Any) -> None:
    """Placeholder audit emit — no-op."""
    pass


class SagaStep:
    """Stub SagaStep class — placeholder."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.args = args
        self.kwargs = kwargs

    @property
    def name(self) -> str:
        """Stub name property — required by test_saga_lra_processor."""
        return self.kwargs.get("name", self.args[0] if self.args else "stub")

    async def forward(self, *args: Any, **kwargs: Any) -> Any:
        """Stub forward step — returns None."""
        return None

    async def compensate(self, *args: Any, **kwargs: Any) -> Any:
        """Stub compensate step — returns None."""
        return None


class SagaProcessor:
    """Stub SagaProcessor class — placeholder."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.args = args
        self.kwargs = kwargs
