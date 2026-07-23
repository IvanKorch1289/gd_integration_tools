"""D11 (Sprint 17): MetricsRegistry — thin re-export из canonical core/utils.

Канонический код живёт в ``src/backend.core.utils.metrics_registry`` (S20 tech-debt
fix: metrics_registry нужен как общий ресурс для обоих слоёв, размещение в
``core/utils/`` делает его доступным без нарушения архитектурных правил).

Этот файл сохранён как backward-compat re-export для ~20 infrastructure-импортёров.
"""

from __future__ import annotations

from src.backend.core.utils.metrics_registry import (  # noqa: F401
    DEFAULT_LABELS,
    MetricsRegistry,
    metrics_registry,
)

__all__ = ("DEFAULT_LABELS", "MetricsRegistry", "metrics_registry")
