"""Prometheus observability для APScheduler (Sprint 16 Wave 5 + S17 K2 W4).

Регистрирует listeners на APScheduler-события и эмитирует метрики:

* ``scheduler_job_executions_total{job_id, status="success|missed|error"}`` —
  каждое выполнение job увеличивает соответствующий counter;
* ``scheduler_jobs_started_total{job_id}`` — отдельный счётчик стартов
  (S17 K2 W4) для расчёта в-flight = started − executed_success − error;
* ``scheduler_jobs_duration_seconds{job_id}`` — гистограмма длительности
  job от submit до executed/error (S17 K2 W4);
* ``scheduler_jobstore_type{type="memory|sqlalchemy"}`` — gauge,
  показывает текущий backend default-jobstore'а; в production-окружении
  ``type="memory"`` логируется как CRITICAL (потеря durable-state).

Интеграция точечная: импортируется и вызывается в lifespan startup
после :func:`SchedulerManager.start`. Не зависит от Prometheus при
отсутствии библиотеки — в этом случае все вызовы становятся no-op.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

__all__ = ("attach_scheduler_metrics", "report_jobstore_type")

_logger = logging.getLogger("infrastructure.scheduler.observability")

_JOB_EXECUTIONS: Any | None = None
_JOBSTORE_TYPE: Any | None = None
_JOB_STARTED: Any | None = None
_JOB_DURATION: Any | None = None
_PROMETHEUS_INIT_FAILED: Final[bool] = False

# Внутренний store submit-времён для расчёта duration. APScheduler не
# передаёт submit-time в EVENT_JOB_EXECUTED, поэтому фиксируем его в
# listener'е EVENT_JOB_SUBMITTED и снимаем в executed/error.
_JOB_SUBMIT_TIMES: dict[str, float] = {}


def _ensure_metrics() -> tuple[Any | None, Any | None]:
    """Lazy-инициализация Prometheus метрик. None если prometheus_client нет."""
    global _JOB_EXECUTIONS, _JOBSTORE_TYPE, _JOB_STARTED, _JOB_DURATION
    if _JOB_EXECUTIONS is not None and _JOBSTORE_TYPE is not None:
        return _JOB_EXECUTIONS, _JOBSTORE_TYPE

    try:
        from src.backend.infrastructure.observability.metrics_registry import (
            metrics_registry,
        )
    except ImportError:
        _logger.debug("MetricsRegistry недоступен — scheduler metrics no-op")
        return None, None

    if _JOB_EXECUTIONS is None:
        _JOB_EXECUTIONS = metrics_registry.counter(
            "scheduler_job_executions_total",
            "Кол-во выполнений APScheduler-job по статусу.",
            labels=("job_id", "status"),
        )

    if _JOB_STARTED is None:
        _JOB_STARTED = metrics_registry.counter(
            "scheduler_jobs_started_total",
            "Кол-во submit'ов APScheduler-job (S17 K2 W4).",
            labels=("job_id",),
        )

    if _JOB_DURATION is None:
        _JOB_DURATION = metrics_registry.histogram(
            "scheduler_jobs_duration_seconds",
            "Длительность APScheduler-job от submit до executed/error.",
            labels=("job_id", "status"),
        )

    if _JOBSTORE_TYPE is None:
        _JOBSTORE_TYPE = metrics_registry.gauge(
            "scheduler_jobstore_type",
            "Тип default-jobstore APScheduler (1 — текущий backend).",
            labels=("type",),
        )

    return _JOB_EXECUTIONS, _JOBSTORE_TYPE


def _emit(counter: Any | None, *, job_id: str, status: str) -> None:
    """Инкремент counter'а с защитой от ошибок prometheus_client."""
    if counter is None:
        return
    try:
        counter.labels(job_id=job_id or "unknown", status=status).inc()
    except Exception as exc:  # noqa: BLE001
        _logger.debug("scheduler counter inc failed: %s", exc)


def attach_scheduler_metrics(scheduler: "AsyncIOScheduler") -> None:
    """Подключает Prometheus-listeners к APScheduler.

    Args:
        scheduler: запущенный :class:`AsyncIOScheduler`.

    Регистрирует 3 listener'а по битовой маске
    :data:`apscheduler.events.EVENT_JOB_EXECUTED |
    EVENT_JOB_ERROR | EVENT_JOB_MISSED` и эмитирует counter
    ``scheduler_job_executions_total`` с label ``status`` равным
    ``success``/``error``/``missed`` соответственно.
    """
    counter, _ = _ensure_metrics()
    if counter is None:
        _logger.info(
            "attach_scheduler_metrics: prometheus_client не установлен — no-op"
        )
        return

    from apscheduler.events import (
        EVENT_JOB_ERROR,
        EVENT_JOB_EXECUTED,
        EVENT_JOB_MISSED,
        EVENT_JOB_SUBMITTED,
    )

    def _observe_duration(event: Any, status: str) -> None:
        """Снять submit_time и записать длительность."""
        if _JOB_DURATION is None:
            return
        job_id = str(event.job_id)
        start = _JOB_SUBMIT_TIMES.pop(job_id, None)
        if start is None:
            return
        elapsed = max(0.0, time.monotonic() - start)
        try:
            _JOB_DURATION.labels(job_id=job_id, status=status).observe(elapsed)
        except Exception as exc:  # noqa: BLE001
            _logger.debug("scheduler duration observe failed: %s", exc)

    def _on_submitted(event: Any) -> None:
        _JOB_SUBMIT_TIMES[str(event.job_id)] = time.monotonic()
        if _JOB_STARTED is not None:
            try:
                _JOB_STARTED.labels(job_id=str(event.job_id or "unknown")).inc()
            except Exception as exc:  # noqa: BLE001
                _logger.debug("scheduler started inc failed: %s", exc)

    def _on_executed(event: Any) -> None:
        _emit(counter, job_id=str(event.job_id), status="success")
        _observe_duration(event, "success")

    def _on_error(event: Any) -> None:
        _emit(counter, job_id=str(event.job_id), status="error")
        _observe_duration(event, "error")
        _logger.error(
            "scheduler.job_error",
            extra={
                "job_id": event.job_id,
                "exception": repr(getattr(event, "exception", None)),
            },
        )

    def _on_missed(event: Any) -> None:
        _emit(counter, job_id=str(event.job_id), status="missed")
        # Missed job не имеет submit_time, дроп из _JOB_SUBMIT_TIMES
        _JOB_SUBMIT_TIMES.pop(str(event.job_id), None)
        _logger.warning(
            "scheduler.job_missed",
            extra={
                "job_id": event.job_id,
                "scheduled_run_time": str(event.scheduled_run_time),
            },
        )

    scheduler.add_listener(_on_submitted, EVENT_JOB_SUBMITTED)
    scheduler.add_listener(_on_executed, EVENT_JOB_EXECUTED)
    scheduler.add_listener(_on_error, EVENT_JOB_ERROR)
    scheduler.add_listener(_on_missed, EVENT_JOB_MISSED)
    _logger.info("Scheduler Prometheus metrics listeners attached")


def report_jobstore_type(*, is_memory: bool, is_production: bool) -> None:
    """Регистрирует тип default-jobstore'а в Prometheus и логирует CRITICAL
    при memory jobstore в production-окружении.

    Args:
        is_memory: ``True`` если default-jobstore — MemoryJobStore.
        is_production: ``True`` если ``APP_ENVIRONMENT=production``.
    """
    _, gauge = _ensure_metrics()
    backend_type = "memory" if is_memory else "sqlalchemy"

    if gauge is not None:
        try:
            gauge.labels(type="memory").set(1.0 if is_memory else 0.0)
            gauge.labels(type="sqlalchemy").set(0.0 if is_memory else 1.0)
        except Exception as exc:  # noqa: BLE001
            _logger.debug("scheduler gauge set failed: %s", exc)

    if is_memory and is_production:
        _logger.critical(
            "scheduler.memory_jobstore_in_production: "
            "APScheduler default-jobstore = MemoryJobStore в production — "
            "scheduled-задачи теряются при рестарте. Установите sync-драйвер "
            "БД для SQLAlchemyJobStore.",
            extra={"jobstore_type": backend_type},
        )
    else:
        _logger.info(
            "scheduler.jobstore_type",
            extra={"jobstore_type": backend_type, "production": is_production},
        )
