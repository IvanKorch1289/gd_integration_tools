"""Capability-checked facade для scheduler manager (S120 W4).

ADR-0207: services/scheduler/cron_dashboard_service.py импортирует
``scheduler_manager`` из ``infrastructure.scheduler``. Этот facade
переносит публичную поверхность в ``core.scheduler``.
"""

from __future__ import annotations

from src.backend.infrastructure.scheduler.scheduler_manager import (  # noqa: F401
    SchedulerManager,
    get_scheduler_manager,
    scheduler_manager,
)

__all__ = ("SchedulerManager", "get_scheduler_manager", "scheduler_manager")
