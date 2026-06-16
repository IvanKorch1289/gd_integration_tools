"""Workflow spec package (S56 W1 decomp from spec.py 636 LOC).

15 Pydantic schemas decomposed в 4 files (per declaration category):
- ``policies.py``: RetryPolicy, SlaPolicy, MemoryScope
- ``activity_declarations.py``: ActivityDeclaration, SagaDeclaration, PauseDeclaration, ResumeDeclaration, SignalWaitDeclaration, SleepDeclaration
- ``advanced_declarations.py``: SensorDeclaration, AgentInvokeDeclaration, ReflectDeclaration, CheckpointDeclaration, GuardrailDeclaration, EscalateDeclaration
- ``workflow.py``: WorkflowDeclaration

Backward-compat: ``from src.backend.dsl.workflow.spec import WorkflowDeclaration`` works.
"""

from __future__ import annotations

from src.backend.dsl.workflow.spec.activity_declarations import (
    ActivityDeclaration,  # S56 W1: re-export
    PauseDeclaration,  # S56 W1: re-export
    ResumeDeclaration,  # S56 W1: re-export
    SagaDeclaration,  # S56 W1: re-export
    SignalWaitDeclaration,  # S56 W1: re-export
    SleepDeclaration,  # S56 W1: re-export
)
from src.backend.dsl.workflow.spec.advanced_declarations import (
    AgentInvokeDeclaration,  # S56 W1: re-export
    CheckpointDeclaration,  # S56 W1: re-export
    EscalateDeclaration,  # S56 W1: re-export
    GuardrailDeclaration,  # S56 W1: re-export
    ReflectDeclaration,  # S56 W1: re-export
    SensorDeclaration,  # S56 W1: re-export
)
from src.backend.dsl.workflow.spec.policies import (
    MemoryScope,  # S56 W1: re-export
    RetryPolicy,  # S56 W1: re-export
    SlaPolicy,  # S56 W1: re-export
)
from src.backend.dsl.workflow.spec.workflow import (
    WorkflowDeclaration,  # S56 W1: re-export
    WorkflowStep,  # S56 W1: re-export
)

__all__ = (
    "WorkflowStep",
    "RetryPolicy",
    "SlaPolicy",
    "MemoryScope",
    "ActivityDeclaration",
    "SagaDeclaration",
    "PauseDeclaration",
    "ResumeDeclaration",
    "SignalWaitDeclaration",
    "SleepDeclaration",
    "SensorDeclaration",
    "AgentInvokeDeclaration",
    "ReflectDeclaration",
    "CheckpointDeclaration",
    "GuardrailDeclaration",
    "EscalateDeclaration",
    "WorkflowDeclaration",
)
