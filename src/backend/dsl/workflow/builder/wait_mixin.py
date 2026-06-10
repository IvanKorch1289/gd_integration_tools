from __future__ import annotations
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

from typing import TYPE_CHECKING, Any, Self

from src.backend.dsl.workflow.spec import (
    ActivityDeclaration,
    MemoryScope,
    PauseDeclaration,
    ResumeDeclaration,
    RetryPolicy,
    SagaDeclaration,
    SensorDeclaration,
    SignalWaitDeclaration,
    SleepDeclaration,
    WorkflowDeclaration,
    WorkflowStep,
)

if TYPE_CHECKING:
    from src.backend.dsl.workflow.gateways import BranchSpec

class WaitMixin:
    """wait/signal/sleep/sensor для WorkflowBuilder. S58 W4 extraction."""

    __slots__ = ()

    def wait_for_signal(
        self,
        signal_name: str,
        *,
        timeout_s: float | None = None,
        output_key: str | None = None,
    ) -> Self:
        """Добавить durable-ожидание внешнего сигнала (HITL)."""
        self._steps.append(
            SignalWaitDeclaration(
                signal_name=signal_name, timeout_s=timeout_s, output_key=output_key
            )
        )
        return self

    def sleep(self, duration_s: float) -> Self:
        """Добавить durable-sleep (Temporal-friendly)."""
        self._steps.append(SleepDeclaration(duration_s=duration_s))
        return self

    def sensor(
        self,
        predicate: str,
        *,
        poll_interval_s: float = 60.0,
        timeout_s: float | None = None,
    ) -> Self:
        """Добавить periodic-sensor (Airflow-style poll-предикат)."""
        self._steps.append(
            SensorDeclaration(
                predicate=predicate,
                poll_interval_s=poll_interval_s,
                timeout_s=timeout_s,
            )
        )
        return self

