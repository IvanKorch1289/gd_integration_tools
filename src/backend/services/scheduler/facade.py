"""SchedulerFacade — capability-checked фасад для scheduler.

Provides capability-checked access to APScheduler for extensions.
"""

from __future__ import annotations

from typing import Any

from src.backend.core.errors import ServiceError
from src.backend.core.logging import get_logger

__all__ = ("SchedulerFacade",)

_logger = get_logger("services.scheduler.facade")


class SchedulerFacade:
    """Capability-checked фасад для scheduler.

    Args:
        capability_check: Опц. callback ``CapabilityGate.check``.
        plugin: Имя caller'а (для capability-event и audit).
    """

    def __init__(
        self, *, capability_check: Any | None = None, plugin: str = "extension"
    ) -> None:
        self._check = capability_check
        self._plugin = plugin

    def _assert(self, action: str, resource: str) -> None:
        if self._check is not None:
            self._check(self._plugin, action, resource)

    def add_job(
        self, job_id: str, func: Any, trigger: str = "cron", **trigger_kwargs: Any
    ) -> None:
        """Добавить задачу в планировщик.

        Args:
            job_id: Уникальный ID задачи.
            func: Callable для выполнения.
            trigger: Тип триггера (cron/interval/date).
            **trigger_kwargs: Аргументы триггера (e.g., hour=9, minute=0).
        """
        self._assert("scheduler.add_job", job_id)
        try:
            from src.backend.core.scheduler import get_scheduler_manager

            manager = get_scheduler_manager()
            manager.add_job(job_id=job_id, func=func, trigger=trigger, **trigger_kwargs)
        except Exception as exc:
            _logger.warning("Failed to add job %s: %s", job_id, exc)
            raise ServiceError(f"Failed to add job: {exc}") from exc

    def remove_job(self, job_id: str) -> None:
        """Удалить задачу из планировщика.

        Args:
            job_id: ID задачи для удаления.
        """
        self._assert("scheduler.remove_job", job_id)
        try:
            from src.backend.core.scheduler import get_scheduler_manager

            manager = get_scheduler_manager()
            manager.remove_job(job_id)
        except Exception as exc:
            _logger.warning("Failed to remove job %s: %s", job_id, exc)
            raise ServiceError(f"Failed to remove job: {exc}") from exc
