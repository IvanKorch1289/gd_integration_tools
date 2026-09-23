from __future__ import annotations

import asyncio
import inspect
import uuid
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from src.backend.core.logging import get_logger
from src.backend.dsl.processors.saga_lra_processor._protocol import (
    _SagaLRAProcessorProtocol,
)
from src.backend.dsl.processors.saga_lra_processor.state import (
    SagaCallable,
    SagaStepSpec,
)


class SagaStepTimeoutError(asyncio.TimeoutError):
    """Saga/LRA step exceeded configured per-step timeout.

    Наследуется от :class:`asyncio.TimeoutError` для backward-compat,
    но имеет конкретный type с метаданными шага для метрик и диагностики
    Saga compensation flow.
    """

    def __init__(
        self, message: str, *, step_name: str, kind: str, timeout_s: float
    ) -> None:
        super().__init__(message)
        self.step_name = step_name
        self.kind = kind
        self.timeout_s = timeout_s


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


class CoreMixin(_SagaLRAProcessorProtocol):
    """core lifecycle methods (state + invoke) для SagaLRAProcessor. S58 W2 extraction."""

    __slots__ = (
        "_fail_fast",
        "_on_state_change",
        "_per_step_timeout",
        "_result_property",
        "_saga_id",
        "_state_property",
        "_steps",
        "_timeout_seconds",
        "name",  # S159 W4: added — BaseProcessor.__init__ sets self.name
    )

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
        # S159 W4: BaseProcessor is NOT in MRO (Protocol chain),
        # so super().__init__() never sets self.name. Set it here.
        self.name = name or f"saga_lra({len(normalized)} steps)"
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

    def _set_state(self, exchange: Exchange[Any], new_state: str) -> None:
        """Set saga state and notify listener (if any)."""
        if new_state not in _VALID_STATES:
            raise ValueError(f"unknown saga state: {new_state!r}")
        old_state = exchange.properties.get(self._state_property)
        exchange.set_property(self._state_property, new_state)
        if old_state != new_state and self._on_state_change is not None:
            try:
                self._on_state_change(old_state or "", new_state, exchange)
            except (
                ImportError,
                AttributeError,
                RuntimeError,
                TypeError,
                ValueError,
            ) as cb_exc:
                # cycle-9/D-AUDIT-960: narrow exceptions + observability.
                # ImportError — callback dep missing, AttributeError — API
                # change, RuntimeError — callback raised, TypeError/ValueError
                # — wrong arg types/values.
                _lra_logger.exception(
                    "SagaLRA on_state_change callback raised: saga_id=%s error=%s",
                    self._saga_id,
                    cb_exc,
                )

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
            # ADR-0305: narrow per-step timeout по оставшемуся DeadlineBudget,
            # если он установлен upstream-middleware (HTTP request deadline).
            effective_timeout = self._per_step_timeout
            try:
                from src.backend.core.request_context import RequestContext

                ctx = RequestContext.current()
                if ctx is not None and ctx.deadline_budget is not None:
                    remaining = ctx.deadline_budget.remaining()
                    if remaining <= 0.0:
                        raise SagaStepTimeoutError(
                            f"Saga '{step_name}' ({kind}) — deadline budget expired",
                            step_name=step_name,
                            kind=kind,
                            timeout_s=0.0,
                        )
                    if effective_timeout is None:
                        effective_timeout = remaining
                    else:
                        effective_timeout = min(effective_timeout, remaining)
            except SagaStepTimeoutError:
                raise
            except Exception:
                # Не ломаем saga-step, если RequestContext недоступен.
                pass

            # ADR-0305: оборачиваем И обёртку, И выполнение в единый try —
            # ``asyncio.wait_for`` поднимает TimeoutError на await, не на wrap.
            try:
                if effective_timeout is not None:
                    coro = asyncio.wait_for(coro, timeout=effective_timeout)
                result = await coro
            except TimeoutError:
                raise SagaStepTimeoutError(
                    f"Saga '{step_name}' ({kind}) exceeded {effective_timeout}s",
                    step_name=step_name,
                    kind=kind,
                    timeout_s=effective_timeout
                    if effective_timeout is not None
                    else 0.0,
                )
        return result
