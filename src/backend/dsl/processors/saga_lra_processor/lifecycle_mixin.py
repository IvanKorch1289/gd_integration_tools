from __future__ import annotations
from __future__ import annotations
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass


import asyncio
import inspect
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any, ClassVar

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




class LifecycleMixin:
    """saga action + compensation для SagaLRAProcessor. S58 W2 extraction."""

    __slots__ = ()

    async def _run_action(
        self,
        step: SagaStepSpec,
        exchange: Exchange[Any],
        context: ExecutionContext,
        *,
        deadline: float,
    ) -> Any:
        """Run the forward action; raise ``SagaLRAError`` on timeout / failure.

        ``deadline`` is the wall-clock absolute cutoff for the overall
        saga; we stop waiting for any single step once it is exceeded.
        """
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise SagaLRAError(f"saga timeout exceeded before step {step['name']!r}")
        # Per-step timeout: use min of (per_step_timeout, remaining).
        step_timeout = self._per_step_timeout
        if step_timeout is not None:
            step_timeout = min(step_timeout, remaining)

        try:
            if step_timeout is not None:
                return await asyncio.wait_for(
                    self._invoke(
                        step["action"],
                        exchange,
                        context,
                        step_name=step["name"],
                        kind="action",
                    ),
                    timeout=step_timeout,
                )
            return await self._invoke(
                step["action"], exchange, context, step_name=step["name"], kind="action"
            )
        except TimeoutError as exc:
            raise SagaLRAError(
                f"step {step['name']!r} action timed out after {step_timeout}s"
            ) from exc



    async def _run_compensation(
        self,
        step: SagaStepSpec,
        exchange: Exchange[Any],
        context: ExecutionContext,
        *,
        ran_compensations: set[str],
    ) -> BaseException | None:
        """Run a compensation, idempotently.

        Returns ``None`` on success, or the exception that was raised.
        Idempotency: if ``step['name']`` is already in
        ``ran_compensations`` we skip and return ``None``.
        """
        comp = step.get("compensation")
        if comp is None:
            ran_compensations.add(step["name"])
            return None
        if step["name"] in ran_compensations:
            _lra_logger.debug(
                "SagaLRA compensation %s already run (idempotent skip)", step["name"]
            )
            return None
        try:
            await self._invoke(
                comp, exchange, context, step_name=step["name"], kind="compensation"
            )
            ran_compensations.add(step["name"])
            return None
        except Exception as exc:
            # Mark as "ran" so a retry won't repeat the same failure,
            # but the caller will see this via the returned exception.
            ran_compensations.add(step["name"])
            _lra_logger.error("SagaLRA compensation %s failed: %s", step["name"], exc)
            return exc

