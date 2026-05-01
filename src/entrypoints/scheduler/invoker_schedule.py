"""Schedule entry-point адаптер для :class:`Invoker` (W22 этап B).

Регистрирует recurring-триггеры (APScheduler ``CronTrigger`` /
``IntervalTrigger``), каждый tick которых вызывает
:class:`Invoker.invoke` с заранее заданным action+payload.

Использование:

.. code-block:: python

    from src.entrypoints.scheduler import (
        ScheduleSpec, register_scheduled_invocation,
    )

    register_scheduled_invocation(
        ScheduleSpec(
            action="health.heartbeat",
            cron="*/5 * * * *",        # каждые 5 минут
            payload={},
            mode="background",
        )
    )

Альтернатива — пакетная загрузка из конфига:

.. code-block:: python

    register_scheduled_invocations([
        ScheduleSpec(action="reports.daily", cron="0 6 * * *"),
        ScheduleSpec(action="cache.warmup", interval_seconds=300),
    ])

Job-id формируется из ``f"scheduled_invocation_{action}"``; повторная
регистрация под тем же id заменяет существующий job (``replace_existing``).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Iterable

__all__ = (
    "ScheduleSpec",
    "register_scheduled_invocation",
    "register_scheduled_invocations",
)

logger = logging.getLogger("entrypoints.scheduler.invoker_schedule")


@dataclass(slots=True)
class ScheduleSpec:
    """Спецификация запланированного вызова Invoker'а.

    Attrs:
        action: ID action'а (передаётся как
            :attr:`InvocationRequest.action`).
        cron: Cron-выражение (5-полевое APScheduler-style:
            ``minute hour day month day_of_week``). Взаимоисключающее
            с ``interval_seconds``.
        interval_seconds: Период в секундах. Взаимоисключающее с ``cron``.
        payload: Полезная нагрузка action'а.
        mode: Режим вызова (значение :class:`InvocationMode`); по
            умолчанию ``"background"`` — fire-and-forget без отслеживания.
        reply_channel: Имя backend'а из ReplyChannelRegistry (опционально).
        metadata: Дополнительные поля для request.metadata
            (напр., routing-target для push-каналов).
        job_id: Override для APScheduler-job_id. По умолчанию
            ``f"scheduled_invocation_{action}"``.
        timezone: Опциональная TZ для cron. ``None`` — TZ scheduler'а.
    """

    action: str
    cron: str | None = None
    interval_seconds: float | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    mode: str = "background"
    reply_channel: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    job_id: str | None = None
    timezone: str | None = None

    def __post_init__(self) -> None:
        if not self.action:
            raise ValueError("ScheduleSpec.action обязателен")
        if bool(self.cron) == bool(self.interval_seconds):
            raise ValueError(
                "ScheduleSpec требует ровно одно из: cron | interval_seconds"
            )
        if self.interval_seconds is not None and self.interval_seconds <= 0:
            raise ValueError("interval_seconds должен быть > 0")


def register_scheduled_invocation(spec: ScheduleSpec) -> str:
    """Регистрирует recurring-job и возвращает его ``job_id``.

    Raises:
        RuntimeError: если APScheduler недоступен.
    """
    from apscheduler.triggers.cron import CronTrigger
    from apscheduler.triggers.interval import IntervalTrigger

    from src.core.di.providers import get_scheduler_manager_provider

    scheduler_manager = get_scheduler_manager_provider()

    trigger: Any
    if spec.cron:
        trigger = CronTrigger.from_crontab(spec.cron, timezone=spec.timezone)
    else:
        trigger = IntervalTrigger(seconds=spec.interval_seconds, timezone=spec.timezone)

    job_id = spec.job_id or f"scheduled_invocation_{spec.action}"
    scheduler_manager.scheduler.add_job(
        _run_scheduled_invocation,
        trigger=trigger,
        kwargs={"spec": spec},
        id=job_id,
        replace_existing=True,
        executor="async",
        jobstore="backup",
    )
    logger.info(
        "Scheduled invocation registered: job_id=%s action=%s cron=%s interval=%s",
        job_id,
        spec.action,
        spec.cron,
        spec.interval_seconds,
    )
    return job_id


def register_scheduled_invocations(specs: Iterable[ScheduleSpec]) -> list[str]:
    """Пакетная регистрация. Возвращает список job_id."""
    return [register_scheduled_invocation(spec) for spec in specs]


async def _run_scheduled_invocation(spec: ScheduleSpec) -> None:
    """Tick-handler: формирует InvocationRequest и зовёт Invoker."""
    from src.core.interfaces.invoker import InvocationMode, InvocationRequest
    from src.services.execution.invoker import get_invoker

    try:
        mode = InvocationMode(spec.mode)
    except ValueError:
        logger.warning(
            "Schedule tick: unknown mode=%r — fallback на background", spec.mode
        )
        mode = InvocationMode.BACKGROUND

    request = InvocationRequest(
        action=spec.action,
        payload=dict(spec.payload),
        mode=mode,
        reply_channel=spec.reply_channel,
        metadata=dict(spec.metadata),
    )
    invoker = get_invoker()
    try:
        await invoker.invoke(request)
    except Exception:  # noqa: BLE001
        logger.exception(
            "Scheduled invocation failed: action=%s job_id=%s",
            spec.action,
            spec.job_id or f"scheduled_invocation_{spec.action}",
        )
