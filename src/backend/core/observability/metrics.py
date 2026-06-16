"""Capability-checked facade для metrics registry (S120 W4).

ADR-0207: services/* observability (metrics.py, sla_alerting.py) импортируют
``metrics_registry`` из ``infrastructure.observability.metrics_registry``.
Этот facade переносит публичную поверхность в ``core.observability``.

Migration path:
- ``from src.backend.infrastructure.observability.metrics_registry import ...``
  → ``from src.backend.core.observability.metrics import ...``
"""

from __future__ import annotations

from src.backend.infrastructure.observability.metrics_registry import (  # noqa: F401
    DEFAULT_LABELS,
    MetricsRegistry,
    metrics_registry,
)

__all__ = ("DEFAULT_LABELS", "MetricsRegistry", "metrics_registry")
