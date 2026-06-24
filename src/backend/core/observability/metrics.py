"""Capability-checked facade для metrics registry (S120 W4).

ADR-0207: services/* observability (metrics.py, sla_alerting.py) импортируют
``metrics_registry`` из ``infrastructure.observability.metrics_registry``.
Этот facade переносит публичную поверхность в ``core.observability``.

Migration path:
- ``from src.backend.infrastructure.observability.metrics_registry import ...``
  → ``from src.backend.core.observability.metrics import ...``
"""

from __future__ import annotations

from src.backend.core.di.providers.infrastructure_facade import (  # noqa: F401
    get_default_labels_attr as _get_default_labels,
    get_metrics_registry_class as _get_metrics_registry_cls,
    get_metrics_registry_factory as _get_metrics_registry_fn,
)
DEFAULT_LABELS = _get_default_labels("DEFAULT_LABELS")
MetricsRegistry = _get_metrics_registry_cls()
metrics_registry = _get_metrics_registry_fn()

__all__ = ("DEFAULT_LABELS", "MetricsRegistry", "metrics_registry")
