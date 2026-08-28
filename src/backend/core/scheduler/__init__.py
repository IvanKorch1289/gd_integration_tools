r"""Capability-checked facade для scheduler manager (S120 W4).

ADR-0207: services/scheduler/cron_dashboard_service.py импортирует
``scheduler_manager`` из ``infrastructure.scheduler``. Этот facade
переносит публичную поверхность в ``core.scheduler``.

Sprint 39 W1 (Phase B Item 7, ADR-0282 §3): removed `validate_cron_expression`
lazy re-export (single cross-layer caller migrated to direct infrastructure
import via ADR-0284 ALLOWED matrix). 3 DI symbols preserved.
"""

from __future__ import annotations as annotations

from src.backend.core.di.providers.infrastructure_locator import (
    get_scheduler_manager_class as _get_sm_cls,
)
from src.backend.core.di.providers.infrastructure_locator import (
    get_scheduler_manager_factory as _get_sm_fn,
)

SchedulerManager = _get_sm_cls()
get_scheduler_manager = _get_scheduler_manager = _get_sm_fn()
scheduler_manager = _get_sm_fn()


__all__ = ("SchedulerManager", "get_scheduler_manager", "scheduler_manager")
