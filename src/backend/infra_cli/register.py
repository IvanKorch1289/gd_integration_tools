"""Connector registry CLI — регистрирует legacy sources/sinks в ConnectorRegistry через HealthAdapter."""
from __future__ import annotations

from src.backend.infrastructure.application.health_aggregator import (
    get_health_aggregator,
)
from src.backend.infrastructure.clients.health_adapter import HealthAdapter
from src.backend.infrastructure.registry import get_registry


def register_connector(name: str, target) -> None:
    """Регистрирует legacy-объект (source/sink/storage) через HealthAdapter в ConnectorRegistry."""
    adapter = HealthAdapter(name=name, target=target)
    get_registry().register(adapter)


def get_aggregator_with_registry():  # Helper for /health endpoint
    agg = get_health_aggregator()
    if not getattr(agg, "_include_registry", False):
        agg.include_registry(True)
    return agg


__all__ = ("register_connector", "get_aggregator_with_registry")
