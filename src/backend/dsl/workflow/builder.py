"""Fluent API для построения :class:`WorkflowDeclaration`.

План V16.2 §4.3 (Sprint 4): Camel/Airflow-style fluent chain поверх
Pydantic-деклараций из :mod:`dsl.workflow.spec`. Не зависит от
``temporalio`` SDK — компиляция декларации в ``@workflow.defn``
выполняется в :mod:`dsl.workflow.compiler` (отдельный шаг).

Пример::

    wf = (
        WorkflowBuilder("credit.assess")
        .description("Оценка заявки клиента")
        .activity("credit.fetch_score", output_key="score")
        .saga()
            .forward("payment.charge")
            .forward("inventory.reserve")
            .compensate("payment.refund")
            .compensate("inventory.release")
        .end_saga()
        .wait_for_signal("manager_approve", timeout_s=3600.0)
        .sleep(5.0)
        .sensor("src.backend.workflows.sensors:is_done", poll_interval_s=10.0)
        .build()
    )
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Self

from src.backend.dsl.workflow.spec import (
    ActivityDeclaration,
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

__all__ = ("SagaBuilder", "WorkflowBuilder")


class WorkflowBuilder:
    """Top-level fluent-builder декларации workflow.

    Методы возвращают ``Self`` для chain-style использования. Финальный
    :meth:`build` производит :class:`WorkflowDeclaration` (Pydantic-валидация
    выполняется именно на этом шаге).
    """

    def __init__(self, name: str, *, description: str | None = None) -> None:
        self._name = name
        self._description = description
        self._steps: list[WorkflowStep] = []
        self._default_timeout_s: float = 300.0
        self._default_retry_policy: RetryPolicy | None = None
        self._sla: Any | None = None

    def description(self, text: str) -> Self:
        """Установить человекочитаемое описание workflow."""
        self._description = text
        return self

    def default_timeout(self, seconds: float) -> Self:
        """Установить default-timeout для activity без explicit ``timeout_s``."""
        self._default_timeout_s = seconds
        return self

    def default_retry(self, policy: RetryPolicy) -> Self:
        """Установить default retry-политику workflow."""
        self._default_retry_policy = policy
        return self

    def sla(
        self,
        *,
        soft_limit_seconds: float,
        hard_limit_seconds: float,
        escalation_email: str | None = None,
        escalation_slack: str | None = None,
        breach_action: str = "alert",
    ) -> Self:
        """Установить SLA-политику workflow (Sprint 9 K3 W10).

        Args:
            soft_limit_seconds: warning threshold.
            hard_limit_seconds: hard threshold (breach_action триггер).
            escalation_email: email для notification на soft breach.
            escalation_slack: Slack channel для notification.
            breach_action: ``alert`` (default) | ``cancel`` | ``none``.
        """
        from src.backend.dsl.workflow.spec import SlaPolicy

        self._sla = SlaPolicy(
            soft_limit_seconds=soft_limit_seconds,
            hard_limit_seconds=hard_limit_seconds,
            escalation_email=escalation_email,
            escalation_slack=escalation_slack,
            breach_action=breach_action,
        )
        return self

    def activity(
        self,
        name: str,
        *,
        args: dict[str, Any] | None = None,
        timeout_s: float | None = None,
        retry_policy: RetryPolicy | None = None,
        output_key: str | None = None,
    ) -> Self:
        """Добавить atomic activity-шаг в цепочку."""
        self._steps.append(
            ActivityDeclaration(
                name=name,
                args=args or {},
                timeout_s=timeout_s,
                retry_policy=retry_policy,
                output_key=output_key,
            )
        )
        return self

    def saga(self) -> SagaBuilder:
        """Открыть саб-builder для saga-шага.

        Завершить вложенный chain нужно через :meth:`SagaBuilder.end_saga`,
        чтобы вернуть управление родительскому ``WorkflowBuilder``.
        """
        return SagaBuilder(self)

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
                signal_name=signal_name,
                timeout_s=timeout_s,
                output_key=output_key,
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

    def gateway_xor(self, *branches: "BranchSpec") -> Self:
        """Добавить XOR (exclusive) gateway — выбирает первую активную ветку.

        Семантика: из переданных веток выполняется **первая**, чьё
        ``condition`` истинно; ветка с ``condition=None`` — fallback.
        Под feature-flag ``workflow_gateways_enabled``.

        Args:
            *branches: Ветки типа :class:`~dsl.workflow.gateways.BranchSpec`.

        Returns:
            Self для chain.
        """
        from src.backend.dsl.workflow.gateways import GatewaySpec  # lazy import

        spec = GatewaySpec(kind="xor", branches=list(branches))
        self._steps.append(spec)  # type: ignore[arg-type]
        return self

    def gateway_and(self, *branches: "BranchSpec") -> Self:
        """Добавить AND (parallel) gateway — параллельный fan-out, ждёт всех.

        Семантика: все ветки запускаются одновременно; workflow
        продолжается только после завершения **всех** веток (join-all).
        Под feature-flag ``workflow_gateways_enabled``.

        Args:
            *branches: Ветки типа :class:`~dsl.workflow.gateways.BranchSpec`.

        Returns:
            Self для chain.
        """
        from src.backend.dsl.workflow.gateways import GatewaySpec  # lazy import

        spec = GatewaySpec(kind="and", branches=list(branches))
        self._steps.append(spec)  # type: ignore[arg-type]
        return self

    def gateway_or(self, *branches: "BranchSpec") -> Self:
        """Добавить OR (inclusive) gateway — ждёт первую активную ветку.

        Семантика: из всех веток с истинным ``condition`` активируются все;
        workflow продолжается после завершения **первой** (wait_any),
        остальные отменяются.
        Под feature-flag ``workflow_gateways_enabled``.

        Args:
            *branches: Ветки типа :class:`~dsl.workflow.gateways.BranchSpec`.

        Returns:
            Self для chain.
        """
        from src.backend.dsl.workflow.gateways import GatewaySpec  # lazy import

        spec = GatewaySpec(kind="or", branches=list(branches))
        self._steps.append(spec)  # type: ignore[arg-type]
        return self

    def build(self) -> WorkflowDeclaration:
        """Собрать и провалидировать :class:`WorkflowDeclaration`.

        Pydantic-валидация выполняется здесь: пустой ``steps``, дубликаты
        и прочие нарушения превращаются в ``pydantic.ValidationError``.
        """
        return WorkflowDeclaration(
            name=self._name,
            description=self._description,
            steps=self._steps,
            default_timeout_s=self._default_timeout_s,
            default_retry_policy=self._default_retry_policy,
            sla=self._sla,
        )


class SagaBuilder:
    """Саб-builder saga-шага. Аккумулирует forward/compensate цепочки.

    Возврат к родителю — через :meth:`end_saga`. Без вызова ``end_saga``
    saga-шаг НЕ попадает в результирующий workflow.
    """

    def __init__(self, parent: WorkflowBuilder) -> None:
        self._parent = parent
        self._forward: list[ActivityDeclaration] = []
        self._compensate: list[ActivityDeclaration] = []

    def forward(
        self,
        name: str,
        *,
        args: dict[str, Any] | None = None,
        timeout_s: float | None = None,
        retry_policy: RetryPolicy | None = None,
        output_key: str | None = None,
    ) -> Self:
        """Добавить forward-activity в saga-цепочку."""
        self._forward.append(
            ActivityDeclaration(
                name=name,
                args=args or {},
                timeout_s=timeout_s,
                retry_policy=retry_policy,
                output_key=output_key,
            )
        )
        return self

    def compensate(
        self,
        name: str,
        *,
        args: dict[str, Any] | None = None,
        timeout_s: float | None = None,
        retry_policy: RetryPolicy | None = None,
    ) -> Self:
        """Добавить compensate-activity (откат forward-шагов)."""
        self._compensate.append(
            ActivityDeclaration(
                name=name,
                args=args or {},
                timeout_s=timeout_s,
                retry_policy=retry_policy,
            )
        )
        return self

    def end_saga(self) -> WorkflowBuilder:
        """Завершить саб-chain и вернуть родительский ``WorkflowBuilder``.

        Pydantic-валидация форвард-цепочки делегируется
        :class:`SagaDeclaration` (минимум 1 forward-шаг обязателен).
        """
        self._parent._steps.append(  # noqa: SLF001 — намеренный delegate-pattern
            SagaDeclaration(forward=self._forward, compensate=self._compensate)
        )
        return self._parent
