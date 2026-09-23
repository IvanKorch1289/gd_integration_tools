"""DSL-процессоры (K3 W3d — agentic patterns, v17 §2.1).

Domain-specific standalone processors (не engine-processors). Каждый
процессор наследует :class:`BaseProcessor` из engine.processors и
предоставляет fluent-цепочку через :mod:`builders.base`.

W2 P0-3 (cycle 152): single-file processors мигрированы в
``src.backend.dsl.engine.processors``. Этот модуль — re-export hub,
импортирующий напрямую из canonical location (НЕ через legacy shim),
чтобы избежать DeprecationWarning при импорте :mod:`dsl.processors`
(как часто делается downstream tooling'ом).

Sprint 36+:

* :class:`BatchProcessor` — bulk insert/update/delete с chunking (S39 W3b).
* :class:`PlanExecuteProcessor` — Plan-and-Execute agentic pattern (v17 §2.1 #2).
* :class:`SagaLRAProcessor` (legacy, mixin-based) — Saga LRA coordinator
  (S38 W3). Это **другая реализация**, не дубликат — Phase 2 ADR pending.

.. deprecated::
    :class:`ClaimCheckProcessor` more полно реализован в
    :class:`src.backend.dsl.engine.processors.eip.transformation.ClaimCheckProcessor`
    (Redis + S3 composite, mode="store"/"retrieve"). Старый S38 W1 SLIM S3-only
    variant удалён в S63 W2 (dedup).

Refs: ADR-0313 (W2 P0-3 Phase 1A pilot + Phase 1B roadmap).
"""

from __future__ import annotations

# W2 P0-3: импортируем напрямую из canonical location (НЕ через legacy shim)
# чтобы избежать DeprecationWarning на каждом import :mod:`dsl.processors`.
from src.backend.dsl.engine.processors.batch_processor import BatchProcessor
from src.backend.dsl.engine.processors.data_lineage import DataLineageProcessor
from src.backend.dsl.engine.processors.plan_execute_processor import (
    PlanExecuteMixin,
    PlanExecuteProcessor,
    PlanResult,
    PlanStep,
)
from src.backend.dsl.engine.processors.reflection_loop_processor import (
    ReflectionLoopProcessor,
)
from src.backend.dsl.engine.processors.router_specialist_processor import (
    RouterSpecialistProcessor,
)
from src.backend.dsl.engine.processors.strangler_fig import StranglerFigProcessor
from src.backend.dsl.processors.saga_lra_processor import SagaLRAProcessor  # legacy другая реализация, Phase 2 ADR

__all__ = (
    "BatchProcessor",
    "DataLineageProcessor",
    "PlanExecuteMixin",
    "PlanExecuteProcessor",
    "PlanResult",
    "PlanStep",
    "ReflectionLoopProcessor",
    "RouterSpecialistProcessor",
    "SagaLRAProcessor",
    "StranglerFigProcessor",
)