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
        "_steps",
        "_timeout_seconds",
        "_per_step_timeout",
        "_result_property",
        "_state_property",
        "_fail_fast",
        "_on_state_change",
        "_saga_id",
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
            except Exception:
                _lra_logger.exception(
                    "SagaLRA on_state_change callback raised: saga_id=%s", self._saga_id
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
            if self._per_step_timeout is not None:
                coro = asyncio.wait_for(coro, timeout=self._per_step_timeout)
            result = await coro
        return result
