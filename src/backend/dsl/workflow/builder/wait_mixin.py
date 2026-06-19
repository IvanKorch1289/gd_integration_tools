from __future__ import annotations

from typing import Self

from src.backend.dsl.workflow.builder._protocol import _WorkflowBuilderProtocol
from src.backend.dsl.workflow.spec import (
    SensorDeclaration,
    SignalWaitDeclaration,
    SleepDeclaration,
)


class WaitMixin(_WorkflowBuilderProtocol):
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

    def human_approval(
        self,
        name: str,
        *,
        approvers_group: str,
        timeout_s: float = 3600.0,
        output_key: str | None = None,
    ) -> Self:
        """HITL (Human-In-The-Loop) approval step (S168 W10 P1-3).

        Semantic alias для ``wait_for_signal`` с naming convention для
        human approval pattern. Использует ``SignalWaitDeclaration``
        с signal_name="approval.{approvers_group}.decided" — same
        payload contract что ``infrastructure.workflow.builder.human_approval``
        (S31 W5).

        Args:
            name: имя шага (уникальное в workflow).
            approvers_group: имя группы аппруверов (per RBAC + HitlService).
            timeout_s: hard timeout (default 1h).
            output_key: ключ в workflow state для payload решения
                (approve/reject + комментарий).
        """
        self._steps.append(
            SignalWaitDeclaration(
                signal_name=f"approval.{approvers_group}.decided",
                timeout_s=timeout_s,
                output_key=output_key or f"hitl_{name}_decision",
            )
        )
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
