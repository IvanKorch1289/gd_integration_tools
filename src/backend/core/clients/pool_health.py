"""Capability-checked facade для pool health monitor (S123 W3).

ADR-0207: services/ai/gateway/pool_registration.py импортирует
``get_pool_monitor`` / ``PoolHealthMonitor`` из
``infrastructure.clients.pool_health``.
"""

from __future__ import annotations

from src.backend.infrastructure.clients.pool_health import (  # noqa: F401
    PoolEntry,
    PoolHealthMonitor,
    get_pool_monitor,
)

__all__ = ("PoolEntry", "PoolHealthMonitor", "get_pool_monitor")
