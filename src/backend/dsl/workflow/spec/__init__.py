"""Workflow spec package (S56 W1 decomp from spec.py 636 LOC).

15 Pydantic schemas decomposed в 4 files (per declaration category):
- ``policies.py``: RetryPolicy, SlaPolicy, MemoryScope
- ``activity_declarations.py``: ActivityDeclaration, SagaDeclaration, PauseDeclaration, ResumeDeclaration, SignalWaitDeclaration, SleepDeclaration
- ``advanced_declarations.py``: SensorDeclaration, AgentInvokeDeclaration, ReflectDeclaration, CheckpointDeclaration, GuardrailDeclaration, EscalateDeclaration
- ``workflow.py``: WorkflowDeclaration

Backward-compat: ``from src.backend.dsl.workflow.spec import WorkflowDeclaration`` works.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

from src.backend.dsl.workflow.spec.policies import RetryPolicy  # S56 W1: re-export
from src.backend.dsl.workflow.spec.policies import SlaPolicy  # S56 W1: re-export
from src.backend.dsl.workflow.spec.policies import MemoryScope  # S56 W1: re-export
from src.backend.dsl.workflow.spec.activity_declarations import ActivityDeclaration  # S56 W1: re-export
from src.backend.dsl.workflow.spec.activity_declarations import SagaDeclaration  # S56 W1: re-export
from src.backend.dsl.workflow.spec.activity_declarations import PauseDeclaration  # S56 W1: re-export
from src.backend.dsl.workflow.spec.activity_declarations import ResumeDeclaration  # S56 W1: re-export
from src.backend.dsl.workflow.spec.activity_declarations import SignalWaitDeclaration  # S56 W1: re-export
from src.backend.dsl.workflow.spec.activity_declarations import SleepDeclaration  # S56 W1: re-export
from src.backend.dsl.workflow.spec.advanced_declarations import SensorDeclaration  # S56 W1: re-export
from src.backend.dsl.workflow.spec.advanced_declarations import AgentInvokeDeclaration  # S56 W1: re-export
from src.backend.dsl.workflow.spec.advanced_declarations import ReflectDeclaration  # S56 W1: re-export
from src.backend.dsl.workflow.spec.advanced_declarations import CheckpointDeclaration  # S56 W1: re-export
from src.backend.dsl.workflow.spec.advanced_declarations import GuardrailDeclaration  # S56 W1: re-export
from src.backend.dsl.workflow.spec.advanced_declarations import EscalateDeclaration  # S56 W1: re-export
from src.backend.dsl.workflow.spec.workflow import WorkflowDeclaration  # S56 W1: re-export

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

WorkflowStep = Annotated[
    ActivityDeclaration
    | SagaDeclaration
    | SignalWaitDeclaration
    | SleepDeclaration
    | PauseDeclaration
    | ResumeDeclaration
    | SensorDeclaration
    | AgentInvokeDeclaration
    | ReflectDeclaration
    | CheckpointDeclaration
    | GuardrailDeclaration
    | EscalateDeclaration,
    Field(discriminator="type"),
]

