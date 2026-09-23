"""S58 W2 — state.py part of saga_lra_processor decomp.

3 small classes: SagaState, SagaLRAError, SagaCompensationError.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any, TypedDict

from src.backend.core.logging import get_logger

if TYPE_CHECKING:
    pass

_lra_logger = get_logger("dsl.saga_lra_processor")


SagaCallable = Callable[..., Awaitable[Any] | Any]


class SagaStepSpec(TypedDict):
    """Нормализованная спецификация шага Saga LRA."""

    name: str
    action: SagaCallable
    compensation: SagaCallable | None


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


class SagaState:
    """String constants for the Saga LRA state machine.

    Prefers module-level constants but also exposed as a class for
    callers that want a namespace import::

        from saga_lra_processor import SagaState
        if state == SagaState.COMPLETED: ...
    """

    RUNNING = STATE_RUNNING
    COMPLETED = STATE_COMPLETED
    COMPENSATING = STATE_COMPENSATING
    COMPENSATED = STATE_COMPENSATED
    FAILED = STATE_FAILED


class SagaLRAError(RuntimeError):
    """Base class for Saga LRA errors."""


class SagaCompensationError(SagaLRAError):
    """Raised when a compensation step itself fails during rollback.

    The ``original_error`` attribute holds the action failure that
    triggered the rollback chain; ``compensation_errors`` is a list of
    ``(step_name, exception)`` tuples for each compensation that failed.
    """

    def __init__(
        self,
        message: str,
        *,
        original_error: BaseException | None = None,
        compensation_errors: list[tuple[str, BaseException]] | None = None,
    ) -> None:
        super().__init__(message)
        self.original_error = original_error
        self.compensation_errors = list(compensation_errors or [])
