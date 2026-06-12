"""S56 W1 — policies.py part of workflow spec decomp.

Schemas: RetryPolicy, SlaPolicy, MemoryScope.

retry + SLA + memory scope policies.
"""

from __future__ import annotations

"""Pydantic-декларации DSL workflow (план V16.2 §4.3, Sprint 4).

Модуль определяет тип-безопасные декларации шагов workflow для
последующей компиляции в Temporal ``@workflow.defn``. Все типы
используют ``discriminator="type"`` для корректной de-сериализации
из YAML/JSON.

Архитектура:
    * Каждый шаг — отдельная Pydantic-модель с дискриминатором ``type``.
    * :class:`WorkflowDeclaration` агрегирует список шагов.
    * Compiler (отдельный модуль) парсит декларацию и эмитит Temporal
      workflow-определение через Jinja2 + ``temporalio.workflow.defn``.

Типы шагов:
    * :class:`ActivityDeclaration` — atomic-задача (Temporal activity).
    * :class:`SagaDeclaration` — forward + compensation цепочка.
    * :class:`SignalWaitDeclaration` — durable ожидание внешнего сигнала.
    * :class:`SleepDeclaration` — durable sleep.
    * :class:`SensorDeclaration` — periodic-предикат с polling-интервалом.
"""

from typing import Literal  # noqa: E402

from pydantic import BaseModel, ConfigDict, Field  # noqa: E402

# S68 W2: RetryPolicy moved в core/ai/retry_policy.py (re-export здесь для
# backward compat — existing imports ``from src.backend.dsl.workflow.spec
# import RetryPolicy`` продолжают работать).
from src.backend.core.ai.retry_policy import RetryPolicy  # noqa: E402

__all__ = ("RetryPolicy", "SlaPolicy", "MemoryScope")


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
