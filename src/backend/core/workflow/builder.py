"""Capability-checked facade для workflow engine (S124 W1).

ADR-0207: extensions/core_entities/orders/workflows/orders_dsl.py импортирует
``WorkflowBuilder`` из ``infrastructure.workflow.builder`` и
``DurableWorkflowProcessor``/``WorkflowStep`` из
``infrastructure.workflow.executor``.

Re-export public surface. Workflow DSL — критичный cross-layer API.
"""

from __future__ import annotations

from src.backend.core.di.providers.infrastructure_facade import (  # noqa: F401
    get_workflow_builder_class as _get_workflow_builder_cls,
    get_dsl_step_executor_class as _get_dsl_step_executor_cls,
    get_durable_workflow_processor_class as _get_durable_wp_cls,
    get_workflow_spec_class as _get_workflow_spec_cls,
    get_workflow_step_class as _get_workflow_step_cls,
)
WorkflowBuilder = _get_workflow_builder_cls()
DSLStepExecutor = _get_dsl_step_executor_cls()
DurableWorkflowProcessor = _get_durable_wp_cls()
WorkflowSpec = _get_workflow_spec_cls()
WorkflowStep = _get_workflow_step_cls()

__all__ = (
    "DSLStepExecutor",
    "DurableWorkflowProcessor",
    "WorkflowBuilder",
    "WorkflowSpec",
    "WorkflowStep",
)
