"""R2.2 — orchestration primitives: saga / sensor.

Domain-agnostic протоколы поверх ``WorkflowBackend`` (Wave D / ADR-045).
Default backend — Temporal (через `WorkflowFacade`); pg-runner — fallback
для dev_light. Этот модуль — Protocol-слой ядра, без heavy SDK.
"""

from src.backend.core.orchestration.saga import (  # noqa: F401 — re-export
    SagaPrimitive,
    SagaResult,
    SagaStep,
)
from src.backend.core.orchestration.sensor import (  # noqa: F401 — re-export
    Sensor,
    SensorTrigger,
)
from src.backend.core.orchestration.temporal_activity_adapter import (
    TemporalActivityWrapper,
    wrap_as_temporal_activity,
)

__all__ = (
    "SagaPrimitive",
    "SagaResult",
    "SagaStep",
    "Sensor",
    "SensorTrigger",
    "TemporalActivityWrapper",
    "wrap_as_temporal_activity",
)
