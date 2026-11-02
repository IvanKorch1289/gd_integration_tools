"""Prometheus-метрики SLA/DLQ для durable-workflow (ADR-0408).

Модуль — единственный источник определения счётчиков
``workflow_sla_compliance_total`` и ``workflow_dlq_publish_total``:

* ``services/workflows/sla_alerting.py`` — чистая оценка SLA (сервисный
  слой, использует :func:`record_workflow_sla_compliance`);
* ``infrastructure/workflow/runner.py`` — рантайм-путь pg-runner'а:
  терминальный переход workflow'а → оценка SLA + публикация в DLQ.

Размещение в ``core`` — чтобы ``infrastructure`` не тянул ``services``
(новый межслойный импорт), а ``services`` не зависел от ``infrastructure``
для доступа к метрике.

Labels ограничены уровнем breach'а и статусом публикации: идентификаторы
workflow/tenant/route в Prometheus-labels не попадают (cardinality +
PII- политика, см. audit 25.09.2026 W9).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from prometheus_client import REGISTRY

from src.backend.core.logging import get_logger
from src.backend.core.observability.metrics import metrics_registry

__all__ = (
    "WorkflowSlaLevel",
    "classify_sla_breach",
    "get_workflow_sla_counter",
    "record_workflow_dlq_publish",
    "record_workflow_sla_compliance",
)

_logger = get_logger("core.observability.workflow_sla")


class WorkflowSlaLevel(StrEnum):
    """Уровень нарушения SLA workflow.

    ``NONE`` — workflow уложился в бюджет; ``SOFT`` — превышен soft-limit;
    ``HARD`` — превышен hard-limit (бюджет времени workflow'а).
    """

    NONE = "none"
    SOFT = "soft"
    HARD = "hard"


_sla_counter = metrics_registry.counter(
    "workflow_sla_compliance_total",
    "SLA evaluations per workflow (level=none/soft/hard)",
    labels=("level",),
)

_dlq_counter = metrics_registry.counter(
    "workflow_dlq_publish_total",
    "Workflow step DLQ publications (status=published/duplicate/no_writer/error)",
    labels=("status",),
)


def _expose_to_default_registry(counter: Any) -> None:
    """Зарегистрировать счётчик в дефолтном ``prometheus_client.REGISTRY``.

    Фабрика ``core.utils.metrics_registry`` создаёт счётчики с
    ``registry=None`` — в текущей версии prometheus_client такой счётчик
    **не** попадает в дефолтный REGISTRY, а значит не отдаётся на
    ``/metrics`` и не виден Prometheus'у (pre-existing долг вне зоны
    кластера, см. ADR-0408 §Последствия). Здесь регистрируем явно, чтобы
    alert-рул получал данные. Дубликат (``Duplicated timeseries``)
    игнорируется — регистрация идемпотентна.
    """
    try:
        REGISTRY.register(counter)
    except ValueError:
        pass


_expose_to_default_registry(_sla_counter)
_expose_to_default_registry(_dlq_counter)


def classify_sla_breach(
    *,
    elapsed_seconds: float,
    soft_limit_seconds: float | None,
    hard_limit_seconds: float,
) -> WorkflowSlaLevel:
    """Классифицировать breach SLA по времени выполнения.

    Args:
        elapsed_seconds: Фактическое время выполнения workflow'а (сек).
        soft_limit_seconds: Soft-limit SLA (сек). ``None`` — soft-уровень
            не используется, breach определяется только по hard-limit.
        hard_limit_seconds: Hard-limit SLA (сек) — бюджет времени workflow'а.

    Returns:
        Уровень breach'а (:class:`WorkflowSlaLevel`).

    """
    if elapsed_seconds >= hard_limit_seconds:
        return WorkflowSlaLevel.HARD
    if soft_limit_seconds is not None and elapsed_seconds >= soft_limit_seconds:
        return WorkflowSlaLevel.SOFT
    return WorkflowSlaLevel.NONE


def get_workflow_sla_counter() -> Any:
    """Вернуть счётчик ``workflow_sla_compliance_total``.

    Доступен для диагностики и тестов (проверка фактического инкремента).

    Returns:
        Объект счётчика Prometheus с label'ом ``level``.

    """
    return _sla_counter


def record_workflow_sla_compliance(level: WorkflowSlaLevel | str) -> None:
    """Инкрементировать ``workflow_sla_compliance_total{level}``.

    Args:
        level: Уровень breach'а (:class:`WorkflowSlaLevel` или его значение).

    """
    value = level.value if isinstance(level, WorkflowSlaLevel) else str(level)
    try:
        _sla_counter.labels(level=value).inc()
    except Exception as exc:  # pragma: no cover — метрика не должна ломать flow
        _logger.debug("workflow_sla.counter_inc_failed: %s", exc)


def record_workflow_dlq_publish(status: str) -> None:
    """Инкрементировать ``workflow_dlq_publish_total{status}``.

    Args:
        status: ``published`` / ``duplicate`` / ``no_writer`` / ``error``.

    """
    try:
        _dlq_counter.labels(status=status).inc()
    except Exception as exc:  # pragma: no cover — метрика не должна ломать flow
        _logger.debug("workflow_dlq.counter_inc_failed: %s", exc)
