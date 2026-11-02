"""Оценка SLA workflow (GAP-WF-4.5, ADR-0403, ADR-0408).

Модуль содержит **чистую** оценку SLA-состояния workflow:

* :class:`SlaBreachLevel` — уровень breach'а (none / soft / hard);
* :class:`SlaBreachRecord` — запись о breach'е (audit / dispatcher);
* :func:`evaluate_sla` — single-pass проверка одного workflow по
  ``elapsed_seconds`` + лимитам SLA; эмитит Prometheus-счётчик
  ``workflow_sla_compliance_total{level}`` (используется дашбордом
  ``infrastructure/observability/grafana/workflow_sla_compliance.json``).

Состояние после волны 22 (ADR-0408)
-----------------------------------
**Gap GAP-WF-4.5 закрыт метрикой + alert-рулом.** Метрика больше не
мёртвая: pg-runner runner' (``infrastructure/workflow/runner.py``)
оценивает SLA каждого терминального перехода workflow'а по бюджету
времени (``__execution_timeout_s`` = SLA hard-limit, ADR-0396) и
инкрементит ``workflow_sla_compliance_total{level}``. Правило алерта
(Prometheus/alertmanager) — ``docs/ops/workflow-sla-alerts.md``; порог
нарушения — из настроек SLO роутов (``route.toml::slo``).

Что по-прежнему **не реализовано**: автоматическая эскалация
(email/Slack) — канала эскалации в репозитории нет. Уведомление об SLA
нарушении доставляется через Prometheus-алерт, а не через почту/Slack.

Исполнитель трекинга (``SlaTracker``) и протокол диспетчера
(``SlaAlertDispatcher``) остались удалёнными как мёртвый код (ADR-0403) —
оценка SLA не требует фонового трекера, потому что выполняется в точке
терминального перехода workflow'а.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from src.backend.core.observability.workflow_sla import (
    WorkflowSlaLevel,
    classify_sla_breach,
    record_workflow_sla_compliance,
)

__all__ = ("SlaBreachLevel", "SlaBreachRecord", "evaluate_sla")

SlaBreachLevel = WorkflowSlaLevel
"""Уровни breach'а SLA (единый источник — ``core.observability.workflow_sla``)."""


@dataclass(slots=True)
class SlaBreachRecord:
    """Запись о breach'е для audit / dispatcher.

    Attributes:
        workflow_id: Temporal workflow ID.
        level: SOFT или HARD.
        elapsed_seconds: время с момента start_at.
        soft_limit: настройка SLA.
        hard_limit: настройка SLA.
        breach_action: что было выполнено (``alert``/``cancel``/``none``).
        detected_at: timestamp обнаружения.

    """

    workflow_id: str
    level: SlaBreachLevel
    elapsed_seconds: float
    soft_limit: float
    hard_limit: float
    breach_action: str = "alert"
    detected_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        """Convert breach record to dictionary.

        Returns:
            Dictionary representation.

        """
        return {
            "workflow_id": self.workflow_id,
            "level": self.level.value,
            "elapsed_seconds": self.elapsed_seconds,
            "soft_limit_seconds": self.soft_limit,
            "hard_limit_seconds": self.hard_limit,
            "breach_action": self.breach_action,
            "detected_at": self.detected_at.isoformat(),
        }


def evaluate_sla(
    *,
    workflow_id: str,
    elapsed_seconds: float,
    soft_limit_seconds: float | None = None,
    hard_limit_seconds: float,
    breach_action: str = "alert",
    tenant_id: str | None = None,
) -> SlaBreachRecord:
    """Single-pass оценка SLA одного workflow.

    Эмитит Prometheus counter ``workflow_sla_compliance_total{level}``
    (level=none/soft/hard) — единственный источник данных для
    Grafana-дашборда и Prometheus-алерта (ADR-0408,
    ``docs/ops/workflow-sla-alerts.md``).

    Args:
        workflow_id: Идентификатор workflow'а (в логи, не в labels).
        elapsed_seconds: Фактическое время выполнения (сек).
        soft_limit_seconds: Soft-limit SLA (сек). ``None`` — soft-уровень
            не используется.
        hard_limit_seconds: Hard-limit SLA (сек).
        breach_action: Что выполнено при breach'е (``alert``/``cancel``).
        tenant_id: Tenant workflow'а (в логи, не в labels).

    Returns:
        :class:`SlaBreachRecord` с ``level=NONE`` если в пределах SLA.

    """
    level = classify_sla_breach(
        elapsed_seconds=elapsed_seconds,
        soft_limit_seconds=soft_limit_seconds,
        hard_limit_seconds=hard_limit_seconds,
    )
    record_workflow_sla_compliance(level)
    return SlaBreachRecord(
        workflow_id=workflow_id,
        level=level,
        elapsed_seconds=elapsed_seconds,
        soft_limit=float(soft_limit_seconds or hard_limit_seconds),
        hard_limit=hard_limit_seconds,
        breach_action=breach_action,
    )
