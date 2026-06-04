"""src.backend.dsl.workflow.builder — auto-generated .pyi stub (Sprint 14 K3 W2).

Этот файл сгенерирован ``tools/gen_dsl_stubs.py`` через runtime
introspection ``WorkflowBuilder``. Не редактировать вручную —
обновляйте через ``make dsl-stubs``.
"""

from __future__ import annotations

from typing import Any, Self

from src.backend.dsl.workflow.gateways import BranchSpec
from src.backend.dsl.workflow.spec import MemoryScope, RetryPolicy, WorkflowDeclaration

class SagaBuilder:
    """Stub for SagaBuilder (defined in .py)."""

    def end_saga(self) -> WorkflowBuilder: ...

class WorkflowBuilder:
    def activity(
        self,
        name: str,
        args: dict[str, Any] | None = ...,
        timeout_s: float | None = ...,
        retry_policy: RetryPolicy | None = ...,
        output_key: str | None = ...,
    ) -> Self:
        """Добавить atomic activity-шаг в цепочку."""
        ...

    def build(self) -> WorkflowDeclaration:
        """Собрать и провалидировать :class:`WorkflowDeclaration`."""
        ...

    def checkpoint(
        self,
        checkpoint_id: str | None = ...,
        include_steps: tuple[str, ...] = (...),
        metadata: dict[str, Any] | None = ...,
        output_key: str | None = ...,
    ) -> Self:
        """Добавить checkpoint-шаг для workflow state persistence (S28 W3)."""
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

    def escalate(
        self,
        to_agent: str | None = ...,
        to_model: str | None = ...,
        reason: str | None = ...,
        output_key: str | None = ...,
    ) -> Self:
        """Добавить escalate-шаг для переключения на другого агента/модель (S28 W3)."""
        ...

    def gateway_and(self, *branches: BranchSpec) -> Self:
        """Добавить AND (parallel) gateway — параллельный fan-out, ждёт всех."""
        ...

    def gateway_or(self, *branches: BranchSpec) -> Self:
        """Добавить OR (inclusive) gateway — ждёт первую активную ветку."""
        ...

    def gateway_xor(self, *branches: BranchSpec) -> Self:
        """Добавить XOR (exclusive) gateway — выбирает первую активную ветку."""
        ...

    def guardrail(
        self,
        rule: str,
        threshold: float,
        on_exceed: str = ...,
        target: str | None = ...,
        output_key: str | None = ...,
    ) -> Self:
        """Добавить guardrail-шаг для лимитов доступа (S28 W3)."""
        ...

    def invoke_agent(
        self,
        agent_id: str,
        input_context: str | None = ...,
        durable: bool = ...,
        output_key: str | None = ...,
        max_turns: int = ...,
        timeout_s: float | None = ...,
        memory_scope: MemoryScope | None = ...,
        write_episode: bool = ...,
        namespace_template: str | None = ...,
        inject_memory: bool = ...,
        recall_on: str | None = ...,
    ) -> Self:
        """Добавить AI-агент как шаг workflow (S27 W6, S28 W2, R-V15-9)."""
        ...

    def pause(self, output_key: str | None = ...) -> Self:
        """Добавить pause-шаг — приостановить workflow через Temporal API (S35 GAP-DSL-2)."""
        ...

    def reflect(
        self,
        trigger: str | None = ...,
        source_step: str | None = ...,
        memory_writes: list[str] | None = ...,
        consolidation_policy: str = ...,
        async_mode: bool = ...,
        output_key: str | None = ...,
    ) -> Self:
        """Добавить reflect-шаг для procedural memory update (S28 W3)."""
        ...

    def resume(self, checkpoint_id: str | None = ...) -> Self:
        """Добавить resume-шаг — возобновить paused workflow (S35 GAP-DSL-2)."""
        ...

    def saga(self) -> SagaBuilder:
        """Открыть саб-builder для saga-шага."""
        ...

    def sensor(
        self,
        predicate: str,
        poll_interval_s: float = ...,
        timeout_s: float | None = ...,
    ) -> Self:
        """Добавить periodic-sensor (Airflow-style poll-предикат)."""
        ...

    def sla(
        self,
        soft_limit_seconds: float,
        hard_limit_seconds: float,
        escalation_email: str | None = ...,
        escalation_slack: str | None = ...,
        breach_action: str = ...,
    ) -> Self:
        """Установить SLA-политику workflow (Sprint 9 K3 W10)."""
        ...

    def sleep(self, duration_s: float) -> Self:
        """Добавить durable-sleep (Temporal-friendly)."""
        ...

    def wait_for_signal(
        self,
        signal_name: str,
        timeout_s: float | None = ...,
        output_key: str | None = ...,
    ) -> Self:
        """Добавить durable-ожидание внешнего сигнала (HITL)."""
        ...
