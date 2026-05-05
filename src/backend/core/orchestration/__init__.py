"""R2.2 — orchestration primitives: saga / retry / deadline / approval / sensor.

Domain-agnostic протоколы поверх ``WorkflowBackend`` (Wave D / ADR-045).
Default backend — Temporal (через `WorkflowFacade`); pg-runner — fallback
для dev_light. Этот модуль — Protocol-слой ядра, без heavy SDK.
"""

from src.backend.core.orchestration.deadline import (
    DeadlinePolicy,
    DeadlineWithEscalation,
)
from src.backend.core.orchestration.human_approval import (
    ApprovalDecision,
    ApprovalRequest,
    HumanApproval,
)
from src.backend.core.orchestration.retry import RetryPolicy, RetryWithCompensation
from src.backend.core.orchestration.saga import SagaPrimitive, SagaResult, SagaStep
from src.backend.core.orchestration.sensor import Sensor, SensorTrigger

__all__ = (
    "ApprovalDecision",
    "ApprovalRequest",
    "DeadlinePolicy",
    "DeadlineWithEscalation",
    "HumanApproval",
    "RetryPolicy",
    "RetryWithCompensation",
    "SagaPrimitive",
    "SagaResult",
    "SagaStep",
    "Sensor",
    "SensorTrigger",
)
