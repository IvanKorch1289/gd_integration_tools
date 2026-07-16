"""Health bridge — lazy accessors for health/pool connectivity.

Extracted from the monolithic ``infrastructure_facade.py`` (S171 decomp).
Each accessor performs a lazy import so that infrastructure modules are
not loaded until first call, preserving import-time isolation (D102).

Covers:
    * ``HealthResult`` / ``HealthMode`` / ``InfrastructureClient`` classes
      (clients.base_connector)
    * ``get_health_check`` factory (application.health_aggregator)
    * pool health monitoring (``PoolEntry``, ``PoolHealthMonitor``, factory)
"""

from __future__ import annotations

from typing import Any

__all__ = (
    "get_health_result_class",
    "get_pool_entry_class",
    "get_pool_health_monitor_class",
    "get_pool_monitor_factory",
    "get_health_mode_class",
    "get_infrastructure_client_class",
    "get_health_check_factory",
)


def get_health_result_class() -> Any:
    """Возвращает ``clients.base_connector.HealthResult`` class."""
    from src.backend.infrastructure.clients.base_connector import HealthResult

    return HealthResult


def get_pool_entry_class() -> Any:
    """Возвращает ``clients.pool_health.PoolEntry`` class."""
    from src.backend.infrastructure.clients.pool_health import PoolEntry

    return PoolEntry


def get_pool_health_monitor_class() -> Any:
    """Возвращает ``clients.pool_health.PoolHealthMonitor`` class."""
    from src.backend.infrastructure.clients.pool_health import PoolHealthMonitor

    return PoolHealthMonitor


def get_pool_monitor_factory() -> Any:
    """Возвращает ``clients.pool_health.get_pool_monitor`` factory."""
    from src.backend.infrastructure.clients.pool_health import get_pool_monitor

    return get_pool_monitor


def get_health_mode_class() -> Any:
    """Возвращает ``clients.base_connector.HealthMode`` class."""
    from src.backend.infrastructure.clients.base_connector import HealthMode

    return HealthMode


def get_infrastructure_client_class() -> Any:
    """Возвращает ``clients.base_connector.InfrastructureClient`` class."""
    from src.backend.infrastructure.clients.base_connector import InfrastructureClient

    return InfrastructureClient


def get_health_check_factory() -> Any:
    """Возвращает ``application.health_aggregator.get_health_check`` factory."""
    from src.backend.infrastructure.application.health_aggregator import get_health_check

    return get_health_check
