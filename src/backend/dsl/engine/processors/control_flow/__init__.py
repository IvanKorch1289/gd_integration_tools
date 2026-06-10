"""Control-flow processors package (S55 W2 decomp from control_flow.py 628 LOC).

8 classes + 4 helpers decomposed в 4 files (per control-flow concept):
- ``choice.py``: ChoiceBranch, ChoiceProcessor, _normalize_choice_branches
- ``flow.py``: TryCatchProcessor, _RetryAbort, RetryProcessor
- ``parallel.py``: PipelineRefProcessor, ParallelProcessor
- ``saga.py``: SagaStep, SagaProcessor, _serialize_sub, _emit_saga_audit

Backward-compat: ``from src.backend.dsl.engine.processors.control_flow import ChoiceProcessor`` works.
"""

from __future__ import annotations

from src.backend.dsl.engine.processors.control_flow.choice import ChoiceBranch  # S55 W2: re-export
from src.backend.dsl.engine.processors.control_flow.choice import ChoiceProcessor  # S55 W2: re-export
from src.backend.dsl.engine.processors.control_flow.choice import _normalize_choice_branches  # S55 W2: re-export
from src.backend.dsl.engine.processors.control_flow.flow import TryCatchProcessor  # S55 W2: re-export
from src.backend.dsl.engine.processors.control_flow.flow import _RetryAbort  # S55 W2: re-export
from src.backend.dsl.engine.processors.control_flow.flow import RetryProcessor  # S55 W2: re-export
from src.backend.dsl.engine.processors.control_flow.parallel import PipelineRefProcessor  # S55 W2: re-export
from src.backend.dsl.engine.processors.control_flow.parallel import ParallelProcessor  # S55 W2: re-export
from src.backend.dsl.engine.processors.control_flow.saga import SagaStep  # S55 W2: re-export
from src.backend.dsl.engine.processors.control_flow.saga import SagaProcessor  # S55 W2: re-export
from src.backend.dsl.engine.processors.control_flow.saga import _serialize_sub  # S55 W2: re-export
from src.backend.dsl.engine.processors.control_flow.saga import _emit_saga_audit  # S55 W2: re-export

__all__ = (
    "ChoiceBranch",
    "ChoiceProcessor",
    "TryCatchProcessor",
    "_RetryAbort",
    "RetryProcessor",
    "PipelineRefProcessor",
    "ParallelProcessor",
    "SagaStep",
    "SagaProcessor",
    "_normalize_choice_branches",
    "_serialize_sub",
    "_emit_saga_audit",
)
