"""Оценка SLA workflow (GAP-WF-4.5, ADR-0403).

Модуль содержит **чистую** оценку SLA-состояния workflow:

* :class:`SlaBreachLevel` — уровень breach'а (none / soft / hard);
* :class:`SlaBreachRecord` — запись о breach'е (audit / dispatcher);
* :func:`evaluate_sla` — single-pass проверка одного workflow по
  ``elapsed_seconds`` + лимитам SLA; эмитит Prometheus-счётчик
  ``workflow_sla_compliance_total{level}`` (используется дашбордом
  ``infrastructure/observability/grafana/workflow_sla_compliance.json``).

Честное состояние (ADR-0403, волна 21)
---------------------------------------
**SLA-алертинг не реализован.** Исполнитель трекинга (класс
``SlaTracker``) и протокол диспетчера ``SlaAlertDispatcher`` удалены как
мёртвый код: они не инстанцировались нигде в ``src/`` (ни в lifespan, ни
в worker'ах, ни в composition root), поэтому soft/hard breach и
эскалация (email/Slack) в рантайме не происходили. ADR-0396 утверждал
обратное («SLA-политика перестала быть инертной») — уточнение здесь.

Почему не поднять исполнителя в этой волне:

* ``WorkflowFacade`` не находится на production-пути старта workflow:
  ``dsl/engine/processors/invoke_workflow.py`` стартует workflow напрямую
  через ``WorkflowBackend``, минуя фасад (вне зоны кластера волны 21);
* канала эскалации (email/Slack) в репозитории нет — единственный
  dispatcher был in-memory тест-дублем;
* поднятие трекера без вызывающего кода = фоновая задача, которая
  ничего не отслеживает (тихое «зелёное» состояние).

Owner-задача: **GAP-WF-4.5** (см. ``docs/roadmap/PROD_READINESS_GAPS.md``,
``docs/roadmap/OWNER_TASKS.md`` § 8, ADR-0403). Минимальный шаг: создать
исполнителя SLA-алертинга (реальный dispatcher + подписка на старт/
завершение workflow) либо удалить ``evaluate_sla`` вместе с дашбордом.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from src.backend.core.logging import get_logger

__all__ = ("SlaBreachLevel", "SlaBreachRecord", "evaluate_sla")

_logger = get_logger("workflow.sla_alerting")


class SlaBreachLevel(StrEnum):
    """SLA breach severity levels."""

    NONE = "none"
    SOFT = "soft"
    HARD = "hard"


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
    soft_limit_seconds: float,
    hard_limit_seconds: float,
    breach_action: str = "alert",
    tenant_id: str | None = None,
) -> SlaBreachRecord:
    """Single-pass оценка SLA одного workflow.

    Sprint 12 K2 W1: дополнительно инкрементирует Prometheus counter
    ``workflow_sla_compliance_total{level}``.

    .. note::
       Вызов в рантайме отсутствует: исполнитель трекинга удалён
       (ADR-0403, owner-задача GAP-WF-4.5). Функция остаётся как чистая
       точка оценки SLA для будущего исполнителя.

    Returns:
        :class:`SlaBreachRecord` с ``level=NONE`` если в пределах SLA.

    """
    if elapsed_seconds >= hard_limit_seconds:
        level = SlaBreachLevel.HARD
    elif elapsed_seconds >= soft_limit_seconds:
        level = SlaBreachLevel.SOFT
    else:
        level = SlaBreachLevel.NONE
    _emit_sla_metric(workflow_id=workflow_id, tenant_id=tenant_id, level=level)
    return SlaBreachRecord(
        workflow_id=workflow_id,
        level=level,
        elapsed_seconds=elapsed_seconds,
        soft_limit=soft_limit_seconds,
        hard_limit=hard_limit_seconds,
        breach_action=breach_action,
    )


_sla_counter: Any | None = None


def _emit_sla_metric(
    *, workflow_id: str, tenant_id: str | None, level: SlaBreachLevel
) -> None:
    """Increment ``workflow_sla_compliance_total{...,level=...}`` counter.

    Lazy-import prometheus_client; при отсутствии — no-op (тесты не
    должны зависеть от prometheus_client).
    """
    global _sla_counter
    if _sla_counter is None:
        try:
            from src.backend.core.observability.metrics import metrics_registry

            # Per audit 25.09.2026 W9: «Запретить tenant_id, workflow_id как
            # Prometheus labels. Их можно помещать в traces/logs с
            # policy-controlled hashing». Cardinality bounded by level only.
            _sla_counter = metrics_registry.counter(
                "workflow_sla_compliance_total",
                "SLA evaluations per workflow (level=none/soft/hard)",
                labels=("level",),
            )
        except (ImportError, ValueError):
            _sla_counter = False  # sentinel: do not retry

    if _sla_counter and _sla_counter is not False:
        try:
            _sla_counter.labels(  # type: ignore[union-attr]
                level=level.value
            ).inc()
        except Exception as exc:
            _logger.debug(
                "sla.counter_inc_failed: %s",
                exc,
                extra={
                    "workflow_id": workflow_id,
                    "tenant_id": tenant_id or "",
                    "level": level.value,
                },
            )
