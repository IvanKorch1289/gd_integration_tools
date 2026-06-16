"""Structural protocol for SagaLRAProcessor mixins.

Breaks the circular dependency between ``SagaLRAProcessor`` and its mixins
and gives mypy enough information about the private attributes/helpers the
mixins use.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

from src.backend.dsl.processors.saga_lra_processor.state import (
    SagaCallable,
    SagaStepSpec,
)


class _SagaLRAProcessorProtocol(Protocol):
    """Common shape expected by SagaLRAProcessor mixins."""

    _steps: list[SagaStepSpec]
    _timeout_seconds: float
    _per_step_timeout: float | None
    _result_property: str
    _state_property: str
    _fail_fast: bool
    _on_state_change: Callable[[str, str, Any], None] | None
    _saga_id: str

    def _set_state(self, exchange: Any, new_state: str) -> None: ...

    async def _invoke(
        self,
        fn: SagaCallable,
        exchange: Any,
        context: Any,
        *,
        step_name: str,
        kind: str,
    ) -> Any: ...

    @staticmethod
    def _normalize_steps(steps: list[SagaStepSpec]) -> list[SagaStepSpec]: ...

    def _publish_result(
        self,
        exchange: Any,
        *,
        completed: list[str],
        failed_step: str | None,
        compensations_run: list[str],
        compensation_errors: list[tuple[str, str]],
        final_state: str,
        error: str | None,
    ) -> None: ...

    async def _run_action(
        self, step: SagaStepSpec, exchange: Any, context: Any, *, deadline: float
    ) -> Any: ...

    async def _run_compensation(
        self,
        step: SagaStepSpec,
        exchange: Any,
        context: Any,
        *,
        ran_compensations: set[str],
    ) -> BaseException | None: ...
