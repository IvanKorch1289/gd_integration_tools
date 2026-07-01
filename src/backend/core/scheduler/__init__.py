"""Capability-checked facade для scheduler manager (S120 W4).

ADR-0207: services/scheduler/cron_dashboard_service.py импортирует
``scheduler_manager`` из ``infrastructure.scheduler``. Этот facade
переносит публичную поверхность в ``core.scheduler``.
"""

from __future__ import annotations

from typing import Any

from src.backend.core.di.providers.infrastructure_facade import (  # noqa: F401
    get_scheduler_manager_class as _get_sm_cls,
    get_scheduler_manager_factory as _get_sm_fn,
)
SchedulerManager = _get_sm_cls()
get_scheduler_manager = _get_scheduler_manager = _get_sm_fn()
scheduler_manager = _get_sm_fn()()


def __getattr__(name: str) -> Any:
    """Lazy re-export validate_cron_expression из infrastructure (ponytail)."""
    if name == "validate_cron_expression":
        from src.backend.infrastructure.scheduler.cron_validator import (
            validate_cron_expression,
        )

        return validate_cron_expression
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = (
    "SchedulerManager",
    "get_scheduler_manager",
    "scheduler_manager",
    "validate_cron_expression",
)
