"""src.backend.dsl.workflow.builder — auto-generated .pyi stub (Sprint 14 K3 W2).

Этот файл сгенерирован ``tools/gen_dsl_stubs.py`` через runtime
introspection ``WorkflowBuilder``. Не редактировать вручную —
обновляйте через ``make dsl-stubs``.
"""

from __future__ import annotations

from typing import Any


class WorkflowBuilder:

    def activity(self, name: str, args: dict[str, Any] | None = ..., timeout_s: float | None = ..., retry_policy: RetryPolicy | None = ..., output_key: str | None = ...) -> Self:
        """Добавить atomic activity-шаг в цепочку."""
        ...

    def build(self) -> WorkflowDeclaration:
        """Собрать и провалидировать :class:`WorkflowDeclaration`."""
        ...

    def default_retry(self, policy: RetryPolicy) -> Self:
        """Установить default retry-политику workflow."""
        ...

    def default_timeout(self, seconds: float) -> Self:
        """Установить default-timeout для activity без explicit ``timeout_s``."""
        ...

    def description(self, text: str) -> Self:
        """Установить человекочитаемое описание workflow."""
        ...

    def gateway_and(self, *branches: 'BranchSpec') -> Self:
        """Добавить AND (parallel) gateway — параллельный fan-out, ждёт всех."""
        ...

    def gateway_or(self, *branches: 'BranchSpec') -> Self:
        """Добавить OR (inclusive) gateway — ждёт первую активную ветку."""
        ...

    def gateway_xor(self, *branches: 'BranchSpec') -> Self:
        """Добавить XOR (exclusive) gateway — выбирает первую активную ветку."""
        ...

    def saga(self) -> SagaBuilder:
        """Открыть саб-builder для saga-шага."""
        ...

    def sensor(self, predicate: str, poll_interval_s: float = ..., timeout_s: float | None = ...) -> Self:
        """Добавить periodic-sensor (Airflow-style poll-предикат)."""
        ...

    def sla(self, soft_limit_seconds: float, hard_limit_seconds: float, escalation_email: str | None = ..., escalation_slack: str | None = ..., breach_action: str = ...) -> Self:
        """Установить SLA-политику workflow (Sprint 9 K3 W10)."""
        ...

    def sleep(self, duration_s: float) -> Self:
        """Добавить durable-sleep (Temporal-friendly)."""
        ...

    def wait_for_signal(self, signal_name: str, timeout_s: float | None = ..., output_key: str | None = ...) -> Self:
        """Добавить durable-ожидание внешнего сигнала (HITL)."""
        ...

