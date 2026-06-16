from __future__ import annotations

from typing import TYPE_CHECKING, Any, Self

from src.backend.dsl.workflow.builder._protocol import _WorkflowBuilderProtocol
from src.backend.dsl.workflow.spec import ActivityDeclaration, RetryPolicy

if TYPE_CHECKING:
    pass


class SlaMixin(_WorkflowBuilderProtocol):
    """SLA + activity config для WorkflowBuilder. S58 W4 extraction."""

    __slots__ = ()

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
