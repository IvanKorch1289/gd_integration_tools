"""TemporalSchedulerBackend stub — placeholder для будущего sprint'а.

Wave ``[wave:s18/w0-goal-driven-sweep-8-scheduler-backend-protocol]``.

Назначение: зарегистрированный backend, который сигнализирует системе,
что Temporal-based scheduling запланирован, но не реализован. Все методы
бросают :class:`NotImplementedError` с прозрачным сообщением.

Реальная реализация — через ``temporalio.client.Client.create_schedule``
(см. ``infrastructure/workflow/temporal_default_impl.py`` для базовой
интеграции с Temporal SDK). Перенос — отдельный sprint после стабилизации
Workflow DSL обёртки над Temporal.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

__all__ = ("TemporalSchedulerBackend",)


_STUB_MESSAGE = (
    "TemporalSchedulerBackend — stub (S18 W0 scaffold). Реальная реализация "
    "ожидается в Sprint TBD. Переключите feature_flags.scheduler_backend="
    "'apscheduler' или используйте :class:`APSchedulerBackend` напрямую."
)


class TemporalSchedulerBackend:
    """Stub реализации :class:`SchedulerBackend` поверх Temporal Schedule API.

    Все методы бросают :class:`NotImplementedError`, чтобы выбор не
    активного backend'а немедленно сигнализировал, а не приводил к
    тихому failure-on-start.
    """

    async def start(self) -> None:
        """Не реализовано."""
        raise NotImplementedError(_STUB_MESSAGE)

    async def stop(self) -> None:
        """Не реализовано."""
        raise NotImplementedError(_STUB_MESSAGE)

    def schedule_cron(
        self,
        name: str,
        cron_expr: str,
        callable_ref: Any,
        *,
        timezone: str = "Europe/Moscow",
        replace_existing: bool = True,
    ) -> str:
        """Не реализовано."""
        raise NotImplementedError(_STUB_MESSAGE)

    def schedule_oneshot(
        self,
        name: str,
        run_at: datetime,
        callable_ref: Any,
        *,
        replace_existing: bool = True,
    ) -> str:
        """Не реализовано."""
        raise NotImplementedError(_STUB_MESSAGE)

    def cancel(self, job_id: str) -> bool:
        """Не реализовано."""
        raise NotImplementedError(_STUB_MESSAGE)

    def list_jobs(self) -> list[dict[str, Any]]:
        """Не реализовано."""
        raise NotImplementedError(_STUB_MESSAGE)
