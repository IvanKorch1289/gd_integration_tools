"""Sprint 5.2 — regression-тесты re-export фасадов ``core/observability``.

Цель: поднять coverage двух <30%-файлов до ≥60%:

* :mod:`core.observability.log_indexer` — re-export ``LogIndexer`` /
  :func:`get_log_indexer` из ``services.io.indexers.log_indexer``.
  Pre: 0% (3 stmts). Post: ≥60%.
* :mod:`core.observability.metrics` — DI-provider facade с
  ``DEFAULT_LABELS`` / :class:`MetricsRegistry` / singleton.
  Pre: 0% (8 stmts). Post: ≥60%.

Использует only public API — никаких internal mocks.
"""

from __future__ import annotations

import pytest

from src.backend.core.observability.log_indexer import LogIndexer as LI_LogIndexer
from src.backend.core.observability.log_indexer import get_log_indexer as li_get
from src.backend.core.observability.metrics import DEFAULT_LABELS
from src.backend.core.observability.metrics import MetricsRegistry as MR_Class
from src.backend.core.observability.metrics import metrics_registry as mr_singleton


class TestLogIndexerFacade:
    """``core.observability.log_indexer`` — re-export facade."""

    def test_log_indexer_class_is_canonical(self) -> None:
        """``LogIndexer`` — тот же класс, что в ``services.io.indexers``."""
        from src.backend.services.io.indexers.log_indexer import LogIndexer

        assert LI_LogIndexer is LogIndexer

    def test_get_log_indexer_is_callable(self) -> None:
        """``get_log_indexer`` — callable factory (lazy-DI)."""
        assert callable(li_get)

    def test_get_log_indexer_requires_app_state(self) -> None:
        """``get_log_indexer()`` бросает ``RuntimeError`` без app.state.

        Factory требует ``search_service`` в ``app.state`` — гарантия
        вызова через FastAPI app lifecycle.
        """
        with pytest.raises(RuntimeError, match="search_service"):
            li_get()


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
