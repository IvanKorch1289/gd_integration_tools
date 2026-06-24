"""Capability-checked facade для scheduler manager (S120 W4).

ADR-0207: services/scheduler/cron_dashboard_service.py импортирует
``scheduler_manager`` из ``infrastructure.scheduler``. Этот facade
переносит публичную поверхность в ``core.scheduler``.
"""

from __future__ import annotations

from src.backend.core.di.providers.infrastructure_facade import (  # noqa: F401
    get_scheduler_manager_class as _get_sm_cls,
    get_scheduler_manager_factory as _get_sm_fn,
)
SchedulerManager = _get_sm_cls()
get_scheduler_manager = _get_scheduler_manager = _get_sm_fn()
scheduler_manager = _get_sm_fn()()

__all__ = ("SchedulerManager", "get_scheduler_manager", "scheduler_manager")
