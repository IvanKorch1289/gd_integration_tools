from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass


import time
from typing import TYPE_CHECKING

from src.backend.core.logging import get_logger
from src.backend.dsl.engine.exchange import ExchangeStatus
from src.backend.dsl.processors.saga_lra_processor.state import (
    SagaCompensationError,
    SagaLRAError,
)

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


class ExecutionMixin:
    """process (BIG 118 LOC) + to_spec для SagaLRAProcessor. S58 W2 extraction."""

    __slots__ = ()

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Run the saga; on failure, compensate completed steps in REVERSE order."""
        # Initial bookkeeping.
        exchange.set_property("saga_id", self._saga_id)
        exchange.set_property("saga_started_at", time.time())
        exchange.set_property("saga_completed_steps", [])
        exchange.set_property("saga_compensations_run", [])
        exchange.set_property("saga_failed_step", None)
        exchange.set_property("saga_error", None)

        self._set_state(exchange, STATE_RUNNING)
        deadline = time.monotonic() + self._timeout_seconds

        completed: list[str] = []
        failed_step: str | None = None
        last_action_error: BaseException | None = None
        ran_compensations: set[str] = set()

        # ── Forward phase ─────────────────────────────────────────
        for step in self._steps:
            try:
                await self._run_action(step, exchange, context, deadline=deadline)
            except Exception as action_exc:
                failed_step = step["name"]
                last_action_error = action_exc
                _lra_logger.error(
                    "SagaLRA step %s failed: %s — compensating",
                    step["name"],
                    action_exc,
                )
                break
            # Camel-style: an action can signal failure by calling
            # ``exchange.fail()`` without raising. Treat that as a
            # forward-step failure too.
            if exchange.status == ExchangeStatus.failed:
                failed_step = step["name"]
                last_action_error = SagaLRAError(
                    exchange.error or f"Step {step['name']!r} marked exchange failed"
                )
                _lra_logger.error(
                    "SagaLRA step %s marked exchange as failed: %s",
                    step["name"],
                    exchange.error,
                )
                break
            completed.append(step["name"])
            exchange.set_property("saga_completed_steps", list(completed))

        # ── Compensation phase (only if any step failed) ─────────
        if failed_step is not None:
            exchange.set_property("saga_failed_step", failed_step)
            exchange.set_property("saga_error", str(last_action_error))
            self._set_state(exchange, STATE_COMPENSATING)

            # Compensate completed steps in REVERSE order.
            compensations_run: list[str] = []
            compensation_errors: list[tuple[str, BaseException]] = []
            # Note: we iterate the original steps list reversed and pick
            # the ones that are in ``completed``. This way we keep the
            # order semantically correct even if we early-break.
            for step in reversed(self._steps):
                if step["name"] not in completed:
                    continue
                exc = await self._run_compensation(
                    step, exchange, context, ran_compensations=ran_compensations
                )
                if step["name"] in compensations_run:
                    continue
                compensations_run.append(step["name"])
                exchange.set_property("saga_compensations_run", list(compensations_run))
                if exc is not None:
                    compensation_errors.append((step["name"], exc))
                    if self._fail_fast:
                        _lra_logger.error(
                            "SagaLRA fail_fast=True, aborting remaining compensations"
                        )
                        break

            # Decide final state.
            final_state = STATE_FAILED if compensation_errors else STATE_COMPENSATED

            exchange.set_property("saga_finished_at", time.time())
            self._publish_result(
                exchange,
                completed=completed,
                failed_step=failed_step,
                compensations_run=compensations_run,
                compensation_errors=[(n, str(e)) for n, e in compensation_errors],
                final_state=final_state,
                error=str(last_action_error) if last_action_error else None,
            )
            self._set_state(exchange, final_state)

            # Mark the exchange as failed (Camel-style) and raise.
            exchange.fail(f"Saga failed at step {failed_step!r}: {last_action_error}")
            wrapped = SagaCompensationError(
                f"Saga failed at step {failed_step!r}",
                original_error=last_action_error,
                compensation_errors=compensation_errors,
            )
            raise wrapped from last_action_error

        # ── Happy path ───────────────────────────────────────────
        exchange.set_property("saga_finished_at", time.time())
        self._publish_result(
            exchange,
            completed=completed,
            failed_step=None,
            compensations_run=[],
            compensation_errors=[],
            final_state=STATE_COMPLETED,
            error=None,
        )
        self._set_state(exchange, STATE_COMPLETED)
        # Mark the exchange completed only if it wasn't already set
        # by one of the steps (which is the common case for sagas).
        if exchange.status not in (ExchangeStatus.completed, ExchangeStatus.failed):
            exchange.complete()

    def to_spec(self) -> dict[str, Any] | None:
        """Serialize to a YAML-compatible spec.

        Since steps are callables (not inner processors), we cannot
        fully round-trip them — we emit a spec containing the step
        names and the configured options, but ``action``/``compensation``
        are dropped with a hint.
        """
        steps_spec: list[dict[str, Any]] = []
        for s in self._steps:
            steps_spec.append(
                {
                    "name": s["name"],
                    "has_compensation": s.get("compensation") is not None,
                }
            )
        return {
            "saga_lra_processor": {
                "saga_id": self._saga_id,
                "steps": steps_spec,
                "timeout_seconds": self._timeout_seconds,
                "per_step_timeout_seconds": self._per_step_timeout,
                "state_property": self._state_property,
                "result_property": self._result_property,
                "fail_fast": self._fail_fast,
            }
        }
