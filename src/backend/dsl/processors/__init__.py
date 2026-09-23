"""DSL-процессоры (K3 W3d — agentic patterns, v17 §2.1).

Domain-specific standalone processors (не engine-processors). Каждый
процессор наследует :class:`BaseProcessor` из engine.processors и
предоставляет fluent-цепочку через :mod:`builders.base`.

W2 P0-3 (cycle 152): single-file + subpackage processors мигрированы в
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

Refs: ADR-0313 (W2 P0-3 Phase 1A pilot), ADR-0314 (Phase 1B), ADR-0315 (Phase 1C).
"""

from __future__ import annotations

# W2 P0-3: импортируем напрямую из canonical location (НЕ через legacy shim)
# чтобы избежать DeprecationWarning на каждом import :mod:`dsl.processors`.
from src.backend.dsl.engine.processors.batch_processor import BatchProcessor
from src.backend.dsl.engine.processors.data_lineage import DataLineageProcessor
from src.backend.dsl.engine.processors.plan_execute_processor import (  # noqa: F401 — re-export
    PlanExecuteMixin,
    PlanExecuteProcessor,
    PlanResult,
    PlanStep,
)
from src.backend.dsl.engine.processors.reflection_loop_processor import (  # noqa: F401 — re-export
    ReflectionLoopProcessor,
)
from src.backend.dsl.engine.processors.router_specialist_processor import (  # noqa: F401 — re-export
    RouterSpecialistProcessor,
)
from src.backend.dsl.engine.processors.strangler_fig import StranglerFigProcessor

# W2 P0-3 Phase 1C: event_store/ и idp_pipeline_processor/ subpackages.
# Re-export from canonical subpackage (НЕ через legacy shim).
from src.backend.dsl.engine.processors.event_store import (  # noqa: F401 — re-export
    CQRSMixin,
    CommandBus,
    Event,
    EventStore,
    EventStoreProcessor,
    EventStream,
    InMemoryEventStore,
    Projection,
    QueryBus,
    get_event_store,
    reset_event_store,
    set_event_store,
)
from src.backend.dsl.engine.processors.idp_pipeline_processor import (  # noqa: F401 — re-export
    IDPPipelineProcessor,
    classify_document,
    extract_fields,
    validate_result,
)

# W2 P0-3 Phase 2: SagaLRAProcessor canonical — saga_lra_processor subpackage
# (mixin-based, state machine с 5 states + SagaCompensationError/SagaLRAError).
# Это ДРУГАЯ реализация, не дубликат current saga_lra.py (single-file).
from src.backend.dsl.engine.processors.saga_lra_processor import (  # noqa: F401 — re-export
    SagaLRAProcessor,
    SagaLRAError,
    SagaCompensationError,
    SagaState,
    SagaStepTimeoutError,
    STATE_RUNNING,
    STATE_COMPLETED,
    STATE_FAILED,
    STATE_COMPENSATING,
    STATE_COMPENSATED,
)

__all__ = (
    "BatchProcessor",
    "CQRSMixin",
    "CommandBus",
    "DataLineageProcessor",
    "Event",
    "EventStore",
    "EventStoreProcessor",
    "EventStream",
    "IDPPipelineProcessor",
    "InMemoryEventStore",
    "PlanExecuteMixin",
    "PlanExecuteProcessor",
    "PlanResult",
    "PlanStep",
    "Projection",
    "QueryBus",
    "ReflectionLoopProcessor",
    "RouterSpecialistProcessor",
    "STATE_COMPENSATED",
    "STATE_COMPENSATING",
    "STATE_COMPLETED",
    "STATE_FAILED",
    "STATE_RUNNING",
    "SagaCompensationError",
    "SagaLRAError",
    "SagaLRAProcessor",
    "SagaState",
    "SagaStepTimeoutError",
    "StranglerFigProcessor",
    "classify_document",
    "extract_fields",
    "get_event_store",
    "reset_event_store",
    "set_event_store",
    "validate_result",
)