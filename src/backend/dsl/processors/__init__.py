"""DSL-процессоры (K3 W3d — agentic patterns, v17 §2.1).

Domain-specific standalone processors (не engine-processors). Каждый
процессор наследует :class:`BaseProcessor` из engine.processors и
предоставляет fluent-цепочку через :mod:`builders.base`.

Sprint 36+:

* :class:`BatchProcessor` — bulk insert/update/delete с chunking (S39 W3b).
* :class:`PlanExecuteProcessor` — Plan-and-Execute agentic pattern (v17 §2.1 #2).
* :class:`SagaLRAProcessor` — Saga LRA coordinator (S38 W3).
* :class:`IdpPipelineProcessor` — IDP pipeline (document processing).

.. deprecated::
    :class:`ClaimCheckProcessor` more полно реализован в
    :class:`src.backend.dsl.engine.processors.eip.transformation.ClaimCheckProcessor`
    (Redis + S3 composite, mode="store"/"retrieve"). Старый S38 W1 SLIM S3-only
    variant удалён в S63 W2 (dedup).
"""

from __future__ import annotations

from src.backend.dsl.processors.batch_processor import BatchProcessor
from src.backend.dsl.processors.plan_execute_processor import (
    PlanExecuteMixin,
    PlanExecuteProcessor,
    PlanResult,
    PlanStep,
)
from src.backend.dsl.processors.saga_lra_processor import SagaLRAProcessor

__all__ = (
    "BatchProcessor",
    "PlanExecuteMixin",
    "PlanExecuteProcessor",
    "PlanResult",
    "PlanStep",
    "SagaLRAProcessor",
)
