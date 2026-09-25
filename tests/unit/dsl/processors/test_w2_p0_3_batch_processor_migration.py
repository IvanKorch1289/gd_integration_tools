"""Focused tests: batch_processor migration W2 P0-3 (cycle 152).

Verifies that legacy ``src.backend.dsl.processors.batch_processor`` теперь
re-export shim, и `BatchProcessor` доступен через оба пути с identical class
identity (для backward-compat).

Note:

* Это pilot для batch_processor — следующие процессоры (strangler_fig,
  data_lineage, plan_execute, reflection_loop, router_specialist,
  event_store, idp_pipeline) будут мигрированы в Phase 1B/C отдельными
  коммитами (см. ADR-0313 roadmap).
"""

from __future__ import annotations

import warnings

from src.backend.dsl.engine.processors.batch_processor import (
    BatchProcessor as CurrentBatchProcessor,
)

# Импорт через LEGACY path триггерит DeprecationWarning.
from src.backend.dsl.processors.batch_processor import (
    BatchProcessor as LegacyBatchProcessor,
)


class TestBatchProcessorIdentity:
    """Legacy и current пути возвращают один и тот же класс."""

    def test_same_identity(self) -> None:
        """Legacy и current импорты возвращают одинаковый класс (no fork)."""
        assert LegacyBatchProcessor is CurrentBatchProcessor

    def test_canonical_module(self) -> None:
        """Canonical location — ``src.backend.dsl.engine.processors.batch_processor``."""
        assert CurrentBatchProcessor.__module__ == (
            "src.backend.dsl.engine.processors.batch_processor"
        )


class TestLegacyDeprecationWarning:
    """Импорт через legacy путь эмитит DeprecationWarning (PEP 702)."""

    def test_legacy_path_emits_deprecation_warning(self) -> None:
        """Новый import через legacy путь → DeprecationWarning."""
        # Импортируем заново с catch_warnings (поскольку модуль уже загружен
        # в test setup — нужно проверить warning на свежем module).
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            # Re-import для триггера warning.
            import importlib

            importlib.reload(
                importlib.import_module("src.backend.dsl.processors.batch_processor")
            )
        deprecation_warnings = [
            x
            for x in w
            if issubclass(x.category, DeprecationWarning)
            and "batch_processor" in str(x.message)
        ]
        assert len(deprecation_warnings) >= 1
        assert "ADR-0313" in str(deprecation_warnings[0].message)


class TestBatchProcessorInstantiation:
    """``BatchProcessor`` через legacy путь инстанциируется без ошибок."""

    def test_class_metadata_accessible_via_legacy(self) -> None:
        """Legacy импорт даёт доступ к class metadata (__name__, __all__)."""
        assert LegacyBatchProcessor.__name__ == "BatchProcessor"
        # Проверяем что class attribute доступны (как минимум side_effect,
        # compensatable из BaseProcessor).
        assert hasattr(LegacyBatchProcessor, "side_effect")
        assert hasattr(LegacyBatchProcessor, "compensatable")
