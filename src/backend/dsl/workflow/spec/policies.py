"""S56 W1 — policies.py part of workflow spec decomp.

Schemas: RetryPolicy, SlaPolicy, MemoryScope.

retry + SLA + memory scope policies.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# S68 W2: RetryPolicy moved в core/ai/retry_policy.py (re-export здесь для
# backward compat — existing imports ``from src.backend.dsl.workflow.spec
# import RetryPolicy`` продолжают работать).
from src.backend.core.ai.retry_policy import RetryPolicy

__all__ = ("MemoryScope", "RetryPolicy", "SlaPolicy")


class SlaPolicy(BaseModel):
    """SLA-политика workflow (Sprint 9 K3 W10 — GAP-WF-4.4).

    Декларируется в ``workflow.yaml::sla``:

    .. code-block:: yaml

        sla:
          soft_limit_seconds: 60.0
          hard_limit_seconds: 300.0
          escalation_email: "ops@bank.local"
          escalation_slack: "#wf-alerts"
          breach_action: alert

    Attributes:
        soft_limit_seconds: warning threshold (логирование + метрика).
        hard_limit_seconds: hard threshold (breach_action + incident).
        escalation_email: куда отправлять email на soft breach.
        escalation_slack: Slack channel для notification.
        breach_action: ``alert`` (default), ``cancel``, ``none``.
    """

    model_config = ConfigDict(extra="forbid")

    soft_limit_seconds: float = Field(gt=0.0)
    hard_limit_seconds: float = Field(gt=0.0)
    escalation_email: str | None = None
    escalation_slack: str | None = None
    breach_action: str = Field(default="alert", pattern=r"^(alert|cancel|none)$")


class MemoryScope(BaseModel):
    """Memory scope policy для :class:`AgentInvokeDeclaration` (S28 W2).

    Pydantic-версия :class:`core.ai.agent_spec.MemoryScope` для
    декларативного использования в YAML workflow definition.

    Attributes:
        read: Кортеж имён memory resources для чтения.
        write: Кортеж имён memory resources для записи.
        mode: Стратегия изоляции (``none`` / ``scoped`` / ``inherited`` / ``shared``).
        write_strategy: Стратегия записи (``hot_path`` / ``background`` / ``manual``).
    """

    model_config = ConfigDict(extra="forbid")

    read: tuple[str, ...] = ()
    write: tuple[str, ...] = ()
    mode: Literal["none", "scoped", "inherited", "shared"] = "scoped"
    write_strategy: Literal["hot_path", "background", "manual"] = "background"
