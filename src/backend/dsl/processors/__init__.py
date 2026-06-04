"""DSL-процессоры (K3 W3d — agentic patterns, v17 §2.1).

Domain-specific standalone processors (не engine-processors). Каждый
процессор наследует :class:`BaseProcessor` из engine.processors и
предоставляет fluent-цепочку через :mod:`builders.base`.

Sprint 36+:

* :class:`BatchProcessor` — bulk insert/update/delete с chunking (S39 W3b).
* :class:`ClaimCheckProcessor` — Claim Check EIP с S3 DI (S38 W1).
* :class:`PlanExecuteProcessor` — Plan-and-Execute agentic pattern (v17 §2.1 #2).
* :class:`SagaLRAProcessor` — Saga LRA coordinator (S38 W3).
* :class:`IdpPipelineProcessor` — IDP pipeline (document processing).
"""

from __future__ import annotations

from src.backend.dsl.processors.batch_processor import BatchProcessor
from src.backend.dsl.processors.claim_check_processor import ClaimCheckProcessor
from src.backend.dsl.processors.plan_execute_processor import (
    PlanExecuteMixin,
    PlanExecuteProcessor,
    PlanResult,
    PlanStep,
)
from src.backend.dsl.processors.saga_lra_processor import SagaLRAProcessor

__all__ = (
    "BatchProcessor",
    "ClaimCheckProcessor",
    "PlanExecuteMixin",
    "PlanExecuteProcessor",
    "PlanResult",
    "PlanStep",
    "SagaLRAProcessor",
)
