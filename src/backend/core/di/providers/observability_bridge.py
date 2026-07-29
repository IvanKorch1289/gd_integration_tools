"""Observability bridge — lazy accessors for ``observability.*`` and logging.

Extracted from the monolithic ``infrastructure_facade.py`` (S171 decomp).
Each accessor performs a lazy import so that infrastructure modules are
not loaded until first call, preserving import-time isolation (D102).

Covers:
    * correlation_id / correlation module
    * client_metrics module
    * metrics_registry (class, singleton, factory, DEFAULT_LABELS)
    * prometheus temporal exporter (class, factory, module, scale gauges)
    * logging (LoggerProtocol, get_logger factory)
"""

from __future__ import annotations

from typing import Any

__all__ = (
    "get_correlation_id",
    "get_client_metrics",
    "get_prometheus_exporter",
    "get_default_labels_tuple",
    "get_metrics_registry_class",
    "get_metrics_registry_singleton",
    "get_prometheus_temporal_exporter_class",
    "get_prometheus_temporal_exporter_factory",
    "get_record_scale_event",
    "get_set_task_queue_depth",
    "get_set_workers_active",
    "get_logger_protocol_class",
    "get_logger_factory",
    "get_default_labels_attr",
    "get_metrics_registry_factory",
    "get_client_metrics_module",
    "get_correlation_module",
)


def get_correlation_id() -> Any:
    """Возвращает текущий correlation_id из contextvar (string).

    Per D102 (single-source-of-truth через facade), provider
    вызывает underlying function и возвращает её value,
    а не саму function.

    S171 M12 R4 #3 fix: ранее возвращалась function <get_correlation_id>,
    что ломало audit_service.emit (test_emit_uses_correlation_id_from_contextvar).
    """
    from src.backend.infrastructure.observability.correlation import (
        get_correlation_id as _get_cid,
    )
    return _get_cid()


def get_client_metrics() -> Any:
    """Возвращает ``observability.client_metrics`` module."""
    from src.backend.infrastructure.observability import client_metrics

    return client_metrics


def get_prometheus_exporter() -> Any:
    """Возвращает ``observability.prometheus_temporal_exporter`` module."""
    from src.backend.infrastructure.observability import prometheus_temporal_exporter

    return prometheus_temporal_exporter


def get_default_labels_tuple() -> Any:
    """Возвращает ``observability.metrics_registry.DEFAULT_LABELS`` tuple.

    Используется в metrics consumers (services/ai/metrics.py,
    services/workflows/sla_alerting.py) для инициализации
    ``MetricsRegistry(default_labels=...)``.
    """
    from src.backend.core.utils.metrics_registry import DEFAULT_LABELS

    return DEFAULT_LABELS


def get_metrics_registry_class() -> Any:
    """Возвращает ``observability.metrics_registry.MetricsRegistry`` class."""
    from src.backend.core.utils.metrics_registry import MetricsRegistry

    return MetricsRegistry


def get_metrics_registry_singleton() -> Any:
    """Возвращает ``observability.metrics_registry.metrics_registry`` singleton."""
    from src.backend.core.utils.metrics_registry import metrics_registry

    return metrics_registry


def get_prometheus_temporal_exporter_class() -> Any:
    """Возвращает legacy exporter class, если он есть в optional backend."""
    from src.backend.infrastructure.observability import prometheus_temporal_exporter

    # Compatibility-only dynamic attribute: current lightweight backend exports
    # functions, while older installations may still provide the class.
    return getattr(prometheus_temporal_exporter, "PrometheusTemporalExporter")


def get_prometheus_temporal_exporter_factory() -> Any:
    """Возвращает legacy exporter factory, если он есть в optional backend."""
    from src.backend.infrastructure.observability import prometheus_temporal_exporter

    return getattr(prometheus_temporal_exporter, "get_prometheus_temporal_exporter")


def get_record_scale_event() -> Any:
    """Возвращает ``observability.prometheus_temporal_exporter.record_scale_event``."""
    from src.backend.infrastructure.observability.prometheus_temporal_exporter import (
        record_scale_event,
    )

    return record_scale_event


def get_set_task_queue_depth() -> Any:
    """Возвращает ``observability.prometheus_temporal_exporter.set_task_queue_depth``."""
    from src.backend.infrastructure.observability.prometheus_temporal_exporter import (
        set_task_queue_depth,
    )

    return set_task_queue_depth


def get_set_workers_active() -> Any:
    """Возвращает ``observability.prometheus_temporal_exporter.set_workers_active``."""
    from src.backend.infrastructure.observability.prometheus_temporal_exporter import (
        set_workers_active,
    )

    return set_workers_active


def get_logger_protocol_class() -> Any:
    """Возвращает ``logging.base.LoggerProtocol`` class."""
    from src.backend.infrastructure.logging.base import LoggerProtocol
    return LoggerProtocol


def get_logger_factory() -> Any:
    """Возвращает ``core.logging.get_logger`` factory."""
    from src.backend.core.logging import get_logger
    return get_logger


def get_default_labels_attr(name: str) -> Any:
    """Возвращает атрибут ``core.utils.metrics_registry.<name>`` (DEFAULT_LABELS).

    Cycle 29 P1-#4 retrospective fix: was importing from
    ``infrastructure.observability`` (removed in cycle 29 commit f02f1f34).
    Now imports from canonical core source.

    Cycle 85 L2 fix: ``from src.backend.core.utils import metrics_registry``
    resolves to the **singleton instance** (because ``__all__`` re-exports
    ``metrics_registry`` the instance alongside ``DEFAULT_LABELS`` and
    ``MetricsRegistry`` the class). Need to use ``importlib`` to get the
    actual module object so ``DEFAULT_LABELS`` (module-level constant)
    can be retrieved.
    """
    import importlib

    module = importlib.import_module("src.backend.core.utils.metrics_registry")
    return getattr(module, name)


def get_metrics_registry_factory() -> Any:
    """Возвращает ``observability.metrics_registry.metrics_registry`` singleton."""
    from src.backend.core.utils.metrics_registry import metrics_registry

    return metrics_registry


def get_client_metrics_module() -> Any:
    """Возвращает ``observability.client_metrics`` module."""
    from src.backend.infrastructure.observability import client_metrics

    return client_metrics


def get_correlation_module() -> Any:
    """Возвращает ``observability.correlation`` module."""
    from src.backend.infrastructure.observability import correlation

    return correlation
