"""Structural protocol for WorkflowBuilder mixins.

Breaks the circular dependency between ``WorkflowBuilder`` and its mixins
and gives mypy enough information about the private attributes the mixins use.
"""

from __future__ import annotations

from typing import Any, Protocol

from src.backend.dsl.workflow.spec import RetryPolicy, WorkflowStep


class _WorkflowBuilderProtocol(Protocol):
    """Common shape expected by WorkflowBuilder mixins."""

    _name: str
    _description: str | None
    _steps: list[WorkflowStep]
    _default_timeout_s: float
    _default_retry_policy: RetryPolicy | None
    _sla: Any | None
