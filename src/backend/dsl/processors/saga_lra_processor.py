"""SagaLRAProcessor — coordinator state machine with compensation tracking.

S38 W3 (Saga LRA / Apache Camel Saga EIP).

Synchronous in-memory version of the Saga LRA coordinator.  Runs a list
of steps sequentially; on the first failure, runs compensations for the
already-succeeded steps in REVERSE order, then transitions the state
machine to a terminal state.

Differences vs. ``src.backend.dsl.engine.processors.saga_lra.SagaLRAProcessor``:

* **Step API is dict-based** (not a ``SagaStep`` dataclass with inner
  processors) — the user passes plain callables, and we drive them
  ourselves. This keeps the class standalone and free of nested
  processor lifecycles.
* **No persistent checkpoints** — purely in-memory. The distributed
  version (with Temporal + ``WorkflowStateRepository``) is V23+ scope.
* **Per-step + overall timeout** enforced via ``asyncio.wait_for``.
* **Idempotent compensations**: a ``compensation_set`` of step names
  that have already been compensated is maintained; if a compensation
  is invoked twice (e.g. from a retry) it becomes a no-op.
* **State machine observable** via ``exchange.properties``: callers
  can introspect ``saga_state``, ``saga_completed_steps``,
  ``saga_failed_step``, ``saga_compensations_run``.

Pattern (Apache Camel Saga EIP / MicroProfile LRA, simplified)::

    saga = SagaLRAProcessor(steps=[
        {"name": "reserve_inventory", "action": reserve, "compensation": release},
        {"name": "charge_card",       "action": charge,  "compensation": refund},
        {"name": "ship_order",        "action": ship,   "compensation": cancel},
    ])
    await saga.process(exchange, context)
"""

from __future__ import annotations

import asyncio
import inspect
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any, ClassVar

from src.backend.core.types.side_effect import SideEffectKind
from src.backend.dsl.engine.exchange import ExchangeStatus
from src.backend.dsl.engine.processors.base import BaseProcessor
from src.backend.infrastructure.logging.factory import get_logger

if TYPE_CHECKING:
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange

__all__ = (
    "SagaCompensationError",
    "SagaLRAError",
    "SagaLRAProcessor",
    "SagaState",
    "SagaStepSpec",
)

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


# ── Step spec type alias ───────────────────────────────────────────────

#: A saga step is a dict with the keys ``name``, ``action``, ``compensation``.
SagaStepSpec = dict[str, Any]

#: A saga action or compensation: sync or async callable
#: accepting ``(exchange, context)``.
SagaCallable = Callable[["Exchange[Any]", "ExecutionContext"], Any | Awaitable[Any]]


# ── Exceptions ─────────────────────────────────────────────────────────


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


# ── Processor ──────────────────────────────────────────────────────────


class SagaLRAProcessor(BaseProcessor):
    """Saga LRA — coordinator state machine with compensation tracking.

    Args:
        steps: List of step dicts, each containing:

            * ``name`` (str, required) — unique step identifier used
              for state-tracking and idempotency.
            * ``action`` (callable, required) — the forward step
              ``(exchange, context) -> Any | Awaitable[Any]``.
            * ``compensation`` (callable, optional) — rollback handler
              ``(exchange, context) -> Any | Awaitable[Any]``. If
              ``None``, no compensation runs for this step on failure.

        timeout_seconds: Maximum total runtime for the whole saga
            (sum of action + compensation time). Default ``300.0``.
        per_step_timeout_seconds: Maximum runtime for a single
            ``action`` call. Default ``30.0``. Set ``None`` to disable
            the per-step bound.
        result_property: Exchange property key where the coordinator
            dumps the final state dict. Default ``"saga_result"``.
        state_property: Exchange property key under which the current
            state is published. Default ``"saga_state"``.
        fail_fast: If ``True``, a compensation failure aborts the
            remaining compensations; if ``False`` (default), the
            processor continues trying all compensations and
            aggregates errors in the final state.
        on_state_change: Optional callback ``(old, new, exchange)``
            invoked at every state transition. Useful for metrics.
        name: Optional processor name.

    Exchange properties set:

        * ``saga_state`` — current state (``running`` / ``completed``
          / ``compensating`` / ``compensated`` / ``failed``).
        * ``saga_completed_steps`` — list of step names that
          succeeded.
        * ``saga_failed_step`` — name of the step that failed (or
          ``None``).
        * ``saga_compensations_run`` — list of step names whose
          compensations were invoked (in invocation order).
        * ``saga_id`` — unique id assigned to this saga instance.
        * ``saga_started_at`` / ``saga_finished_at`` — wall-clock
          timestamps (``time.time()``).
        * ``saga_error`` — the error string of the failing action.
        * ``saga_result`` — the full state dict (set on completion).

    Behavior:

        * Each ``action`` runs under ``asyncio.wait_for(per_step_timeout)``.
        * If the total elapsed time exceeds ``timeout_seconds`` the
          saga is aborted and compensations run for the
          already-succeeded steps.
        * Compensations are invoked in REVERSE order of the steps
          that succeeded.
        * Each compensation is **idempotent** — invoking a
          compensation whose name is already in
          ``saga_compensations_run`` is a no-op.
        * If any compensation raises, the error is recorded in
          ``SagaCompensationError.compensation_errors`` and the final
          state becomes ``"failed"`` (unless ``fail_fast=False``
          changes semantics — see arg).
        * On terminal failure, the original action error is re-raised
          wrapped in :class:`SagaCompensationError`.
    """

    side_effect: ClassVar[SideEffectKind] = SideEffectKind.SIDE_EFFECTING
    compensatable: ClassVar[bool] = True

    def __init__(
        self,
        *,
        steps: list[SagaStepSpec],
        timeout_seconds: float = 300.0,
        per_step_timeout_seconds: float | None = 30.0,
        result_property: str = "saga_result",
        state_property: str = "saga_state",
        fail_fast: bool = False,
        on_state_change: Callable[[str, str, Exchange[Any]], None] | None = None,
        name: str | None = None,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError(
                f"timeout_seconds должен быть > 0, получено {timeout_seconds!r}"
            )
        if per_step_timeout_seconds is not None and per_step_timeout_seconds <= 0:
            raise ValueError(
                "per_step_timeout_seconds должен быть > 0 или None, "
                f"получено {per_step_timeout_seconds!r}"
            )
        normalized = self._normalize_steps(steps)
        super().__init__(name=name or f"saga_lra({len(normalized)} steps)")
        self._steps: list[SagaStepSpec] = normalized
        self._timeout_seconds = float(timeout_seconds)
        self._per_step_timeout = (
            float(per_step_timeout_seconds)
            if per_step_timeout_seconds is not None
            else None
        )
        self._result_property = result_property
        self._state_property = state_property
        self._fail_fast = bool(fail_fast)
        self._on_state_change = on_state_change
        self._saga_id = uuid.uuid4().hex

    # ── Validation helpers ─────────────────────────────────────────

    @staticmethod
    def _normalize_steps(steps: list[SagaStepSpec]) -> list[SagaStepSpec]:
        """Validate step list and return a normalized copy.

        Normalization:

        * Strips non-essential keys (e.g. comments), keeps ``name``,
          ``action``, ``compensation``.
        * Generates a default name (``step_N``) if missing.
        * Detects duplicate names and empty ``action`` callables.
        """
        if not isinstance(steps, list):
            raise TypeError(f"steps должен быть list, получено {type(steps).__name__}")
        seen: set[str] = set()
        normalized: list[SagaStepSpec] = []
        for i, raw in enumerate(steps):
            if not isinstance(raw, dict):
                raise TypeError(
                    f"step #{i} должен быть dict, получено {type(raw).__name__}"
                )
            action = raw.get("action")
            if not callable(action):
                raise ValueError(
                    f"step #{i}: 'action' должен быть callable, "
                    f"получено {type(action).__name__}"
                )
            compensation = raw.get("compensation")
            if compensation is not None and not callable(compensation):
                raise ValueError(
                    f"step #{i}: 'compensation' должен быть callable или None, "
                    f"получено {type(compensation).__name__}"
                )
            name = raw.get("name") or f"step_{i}"
            if not isinstance(name, str):
                raise ValueError(
                    f"step #{i}: 'name' должен быть str, получено {type(name).__name__}"
                )
            if name in seen:
                raise ValueError(f"step #{i}: дубликат name {name!r}")
            seen.add(name)
            normalized.append(
                {"name": name, "action": action, "compensation": compensation}
            )
        return normalized

    # ── State machine helpers ──────────────────────────────────────

    def _set_state(self, exchange: Exchange[Any], new_state: str) -> None:
        """Set saga state and notify listener (if any)."""
        if new_state not in _VALID_STATES:
            raise ValueError(f"unknown saga state: {new_state!r}")
        old_state = exchange.properties.get(self._state_property)
        exchange.set_property(self._state_property, new_state)
        if old_state != new_state and self._on_state_change is not None:
            try:
                self._on_state_change(old_state or "", new_state, exchange)
            except Exception:
                _lra_logger.exception(
                    "SagaLRA on_state_change callback raised: saga_id=%s", self._saga_id
                )

    def _publish_result(
        self,
        exchange: Exchange[Any],
        *,
        completed: list[str],
        failed_step: str | None,
        compensations_run: list[str],
        compensation_errors: list[tuple[str, str]],
        final_state: str,
        error: str | None,
    ) -> None:
        """Publish the full saga state under ``result_property``."""
        result = {
            "saga_id": self._saga_id,
            "state": final_state,
            "completed_steps": list(completed),
            "failed_step": failed_step,
            "compensations_run": list(compensations_run),
            "compensation_errors": list(compensation_errors),
            "error": error,
            "total_steps": len(self._steps),
        }
        exchange.set_property(self._result_property, result)

    # ── Action / compensation runners ─────────────────────────────

    async def _invoke(
        self,
        fn: SagaCallable,
        exchange: Exchange[Any],
        context: ExecutionContext,
        *,
        step_name: str,
        kind: str,
    ) -> Any:
        """Run a sync or async callable with the configured per-step timeout.

        ``kind`` is "action" or "compensation" — purely for logging.
        """
        result = fn(exchange, context)
        if inspect.isawaitable(result):
            coro = result
            if self._per_step_timeout is not None:
                coro = asyncio.wait_for(coro, timeout=self._per_step_timeout)
            result = await coro
        return result

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

    # ── Main entrypoint ───────────────────────────────────────────

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

    # ── Serialization ─────────────────────────────────────────────

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
