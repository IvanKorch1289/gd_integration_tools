from __future__ import annotations

"""SagaLRAProcessor package (S58 W2 decomp from saga_lra_processor.py 587 LOC).

9 methods decomposed в 4 mixin files (3 small classes в state.py):
- ``state.py``: SagaState, SagaLRAError, SagaCompensationError
- ``core_mixin.py`` (3): __init__, _set_state, _invoke
- ``lifecycle_mixin.py`` (2): _run_action, _run_compensation
- ``serialization_mixin.py`` (2): _normalize_steps, _publish_result
- ``execution_mixin.py`` (2): process (BIG 118 LOC), to_spec

Backward-compat: ``from src.backend.dsl.processors.saga_lra_processor import SagaLRAProcessor`` works.
"""


from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass


import asyncio
import inspect
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, ClassVar

from src.backend.core.logging import get_logger
from src.backend.core.types.side_effect import SideEffectKind
from src.backend.dsl.engine.exchange import ExchangeStatus
from src.backend.dsl.engine.processors.base import BaseProcessor

if TYPE_CHECKING:
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange


_lra_logger = get_logger("dsl.saga_lra_processor")

# ── State machine constants ────────────────────────────────────────────

#: Terminal success state.
STATE_COMPLETED = "completed"
#: Transient state during compensation.
STATE_COMPENSATING = "compensating"
#: All compensations ran successfully.
STATE_COMPENSATED = "compensated"
#: At least one compensation itself failed.
STATE_FAILED = "failed"
#: Active forward execution.
STATE_RUNNING = "running"

# All known states (used for validation).
_VALID_STATES = frozenset(
    {
        STATE_RUNNING,
        STATE_COMPLETED,
        STATE_COMPENSATING,
        STATE_COMPENSATED,
        STATE_FAILED,
    }
)


from src.backend.dsl.processors.saga_lra_processor.core_mixin import (
    CoreMixin,  # S58 W2: MRO
)
from src.backend.dsl.processors.saga_lra_processor.execution_mixin import (
    ExecutionMixin,  # S58 W2: MRO
)
from src.backend.dsl.processors.saga_lra_processor.lifecycle_mixin import (
    LifecycleMixin,  # S58 W2: MRO
)
from src.backend.dsl.processors.saga_lra_processor.serialization_mixin import (
    SerializationMixin,  # S58 W2: MRO
)
from src.backend.dsl.processors.saga_lra_processor.state import (
    SagaCompensationError,  # S58 W2: re-export
    SagaLRAError,  # S58 W2: re-export
    SagaState,  # S58 W2: re-export
)

__all__ = ("SagaCompensationError", "SagaLRAError", "SagaLRAProcessor", "SagaState")


class SagaLRAProcessor(CoreMixin, LifecycleMixin, SerializationMixin, ExecutionMixin):
    """Saga LRA processor (4 mixins = 6 methods + 3 core)."""

    __slots__ = ()
