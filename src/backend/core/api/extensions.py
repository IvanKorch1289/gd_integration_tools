"""Sprint 33 Sprint D.1: layer violation remediation facade.

Ponytail fix: re-exports dsl.* symbols через core.api.extensions,
чтобы entrypoints могли соблюдать boundary rule
(extensions → core only, never dsl.*).

До Sprint 33: 42 entrypoints → dsl.* violations.
После: 0 (после migration в Sprint D.2).
"""
from __future__ import annotations

# Action registry (8 violations → 0)
from src.backend.dsl.commands.action_registry import (
    ActionHandlerRegistry,
    ActionHandlerSpec,
    action_handler_registry,
)
from src.backend.dsl.commands.action_registry import ActionCommandSchema

# Commands registry — RouteRegistry canonical (14 violations → 0)
from src.backend.dsl.commands.registry import RouteRegistry

# Workflow builder (3+ violations → 0)
from src.backend.dsl.workflow.builder import (
    ActivityDeclaration,
    RetryPolicy,
    SagaBuilder,
    SagaDeclaration,
    WorkflowBuilder,
)

# Workflow spec (entrypoints → dsl.workflow.spec.workflow)
from src.backend.dsl.workflow.spec.workflow import (
    WorkflowDeclaration,
    WorkflowStep,
)

# Engine primitives (6 violations → 0)
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.execution_engine import ExecutionEngine

# YAML I/O (3 violations → 0)
from src.backend.dsl.workflow.yaml_io import to_yaml, from_yaml
from src.backend.dsl.yaml_store import YAMLStore


__all__ = [
    # Action registry
    "ActionHandlerRegistry",
    "ActionHandlerSpec",
    "action_handler_registry",
    "ActionCommandSchema",
    # Route registry
    "RouteRegistry",
    # Workflow builder
    "ActivityDeclaration",
    "RetryPolicy",
    "SagaBuilder",
    "SagaDeclaration",
    "WorkflowBuilder",
    # Workflow spec
    "WorkflowDeclaration",
    "WorkflowStep",
    # Engine
    "ExecutionContext",
    "Exchange",
    "ExecutionEngine",
    # YAML
    "to_yaml",
    "from_yaml",
    "YAMLStore",
]
