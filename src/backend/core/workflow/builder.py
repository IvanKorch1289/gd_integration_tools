"""Capability-checked facade для workflow engine (S124 W1).

ADR-0207: extensions/core_entities/orders/workflows/orders_dsl.py импортирует
``WorkflowBuilder`` из ``infrastructure.workflow.builder`` и
``DurableWorkflowProcessor``/``WorkflowStep`` из
``infrastructure.workflow.executor``.

Re-export public surface. Workflow DSL — критичный cross-layer API.
"""

from __future__ import annotations

from src.backend.infrastructure.workflow.builder import (  # noqa: F401
    WorkflowBuilder,
)
from src.backend.infrastructure.workflow.executor import (  # noqa: F401
    DSLStepExecutor,
    DurableWorkflowProcessor,
    WorkflowSpec,
    WorkflowStep,
)

__all__ = (
    "DSLStepExecutor",
    "DurableWorkflowProcessor",
    "WorkflowBuilder",
    "WorkflowSpec",
    "WorkflowStep",
)
