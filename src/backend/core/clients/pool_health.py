"""Capability-checked facade для pool health monitor (S123 W3).

ADR-0207: services/ai/gateway/pool_registration.py импортирует
``get_pool_monitor`` / ``PoolHealthMonitor`` из
``infrastructure.clients.pool_health``.
"""

from __future__ import annotations

from src.backend.core.di.providers.infrastructure_facade import (  # noqa: F401
    get_pool_entry_class as _get_pe_cls,
    get_pool_health_monitor_class as _get_phm_cls,
    get_pool_monitor_factory as _get_pm_fn,
)
PoolEntry = _get_pe_cls()
PoolHealthMonitor = _get_phm_cls()
get_pool_monitor = _get_pm_fn()

__all__ = ("PoolEntry", "PoolHealthMonitor", "get_pool_monitor")
