"""Protocol :class:`SchedulerBackend` — абстракция над APScheduler/Temporal.

Wave ``[wave:s18/w0-goal-driven-sweep-8-scheduler-backend-protocol]``.

Назначение: явный контракт между application-кодом (admin REST,
DSL-процессоры, scheduled-tasks) и конкретной реализацией планировщика.
Позволяет переключать backend (APScheduler default → Temporal в будущем)
через feature-flag без переписывания callsite'ов.

Реализации:

* :class:`src.backend.infrastructure.scheduler.apscheduler_backend.
  APSchedulerBackend` — обёртка над существующим
  :class:`SchedulerManager` (production-готова).
* :class:`src.backend.infrastructure.scheduler.temporal_scheduler_backend.
  TemporalSchedulerBackend` — stub (carryover в будущий sprint).

Выбор backend задаётся через ``feature_flags.scheduler_backend``
(:class:`Literal["apscheduler", "temporal"]`), default — ``apscheduler``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol, runtime_checkable

__all__ = ("ScheduledJob", "SchedulerBackend")


class ScheduledJob:
    """Лёгкий DTO для описания scheduled job в Protocol-возвращаемых списках.

    Attributes:
        id: Уникальный идентификатор job'а.
        name: Человеко-читаемое имя.
        next_run_time: ISO-строка следующего запуска (None если paused).
        trigger: Текстовое описание триггера (``cron[...]`` / ``date[...]``).
        paused: True если job приостановлен.
    """

    __slots__ = ("id", "name", "next_run_time", "paused", "trigger")

    def __init__(
        self,
        *,
        id: str,
        name: str,
        next_run_time: str | None,
        trigger: str,
        paused: bool,
    ) -> None:
        """Инициализация ScheduledJob DTO.

        Args:
            id: Уникальный идентификатор job'а.
            name: Человеко-читаемое имя.
            next_run_time: ISO-строка следующего запуска (None если paused).
            trigger: Текстовое описание триггера.
            paused: True если job приостановлен.
        """
        self.id = id
        self.name = name
        self.next_run_time = next_run_time
        self.trigger = trigger
        self.paused = paused

    def to_dict(self) -> dict[str, Any]:
        """Сериализация в dict для admin REST / Streamlit pages."""
        return {
            "id": self.id,
            "name": self.name,
            "next_run_time": self.next_run_time,
            "trigger": self.trigger,
            "paused": self.paused,
        }


@runtime_checkable
class SchedulerBackend(Protocol):
    """Контракт планировщика задач (APScheduler/Temporal/in-memory).

    Все методы могут вызываться из async-кода; sync-методы исполняются
    в worker-thread (через ``asyncio.to_thread`` если backend требует).
    """

    async def start(self) -> None:
        """Запустить планировщик (idempotent)."""

    async def stop(self) -> None:
        """Остановить планировщик (idempotent)."""

    def schedule_cron(
        self,
        name: str,
        cron_expr: str,
        callable_ref: Any,
        *,
        timezone: str = "Europe/Moscow",
        replace_existing: bool = True,
    ) -> str:
        """Зарегистрировать cron-job.

        Args:
            name: Идентификатор и имя job'а.
            cron_expr: cron-строка в формате croniter.
            callable_ref: Функция/корутина для вызова.
            timezone: IANA-имя tz.
            replace_existing: При True перезаписать существующую job
                с тем же id.

        Returns:
            ``job_id`` зарегистрированной задачи.
        """

    def schedule_oneshot(
        self,
        name: str,
        run_at: datetime,
        callable_ref: Any,
        *,
        replace_existing: bool = True,
    ) -> str:
        """Зарегистрировать одноразовый job на конкретный момент времени.

        Args:
            name: Идентификатор и имя job'а.
            run_at: Datetime запуска (включая tz).
            callable_ref: Функция/корутина для вызова.
            replace_existing: При True перезаписать существующую job
                с тем же id.

        Returns:
            ``job_id`` зарегистрированной задачи.
        """

    def cancel(self, job_id: str) -> bool:
        """Отменить job по идентификатору.

        Args:
            job_id: Идентификатор job'а.

        Returns:
            True если job был найден и удалён, иначе False.
        """

    def list_jobs(self) -> list[dict[str, Any]]:
        """Получить список зарегистрированных jobs.

        Returns:
            Список dict-DTO с полями id/name/next_run_time/trigger/paused.
        """
