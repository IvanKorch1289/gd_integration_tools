"""Sprint 5.2 — regression-тесты re-export фасадов ``core/observability``.

Цель: поднять coverage двух <30%-файлов до ≥60%:

* :mod:`core.observability.metrics` — DI-provider facade с
  ``DEFAULT_LABELS`` / :class:`MetricsRegistry` / singleton.
  Pre: 0% (8 stmts). Post: ≥60%.

Note (Sprint 40 W1 Item 6b): ``core.observability.log_indexer`` proxy REMOVED
(Sprint 38 W2 commit ``3f21b2fc`` per ADR-0282 Phase B Item 6). Single caller
``infrastructure/audit/event_log.py:195`` migrated to direct infra import.
``log_indexer`` regression tests REMOVED from this file (proxy НЕ существует).

Использует only public API — никаких internal mocks.
"""

from __future__ import annotations

import pytest

from src.backend.core.observability.metrics import DEFAULT_LABELS
from src.backend.core.observability.metrics import MetricsRegistry as MR_Class
from src.backend.core.observability.metrics import metrics_registry as mr_singleton


class TestMetricsFacade:
    """``core.observability.metrics`` — DI-provider facade."""

    def test_default_labels_is_non_empty_tuple(self) -> None:
        """``DEFAULT_LABELS`` — tuple с хотя бы одним label-name."""
        assert isinstance(DEFAULT_LABELS, tuple)
        assert len(DEFAULT_LABELS) >= 1
        assert all(isinstance(label, str) for label in DEFAULT_LABELS)

    def test_metrics_registry_class_is_constructible(self) -> None:
        """``MetricsRegistry`` — class, можно инстанциировать."""
        assert isinstance(MR_Class, type)
        instance = MR_Class()
        assert instance is not None

    def test_metrics_registry_singleton_is_resolved(self) -> None:
        """``metrics_registry`` — singleton instance той же registry-class."""
        assert isinstance(mr_singleton, MR_Class)

    def test_get_metrics_registry_factory_returns_singleton(self) -> None:
        """``get_metrics_registry_factory()`` возвращает тот же singleton."""
        from src.backend.core.di.providers.infrastructure_locator import (
            get_metrics_registry_factory,
        )

        # Lazy-provider уже resolved → возвращает сам singleton.
        assert get_metrics_registry_factory() is mr_singleton
