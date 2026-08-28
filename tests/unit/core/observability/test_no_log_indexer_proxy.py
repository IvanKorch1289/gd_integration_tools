"""Regression tests для core.observability.log_indexer proxy removal (Sprint 38 W2, ADR-0282 Phase B Item 6).

Покрывает:
1. `core/observability/log_indexer` proxy fully removed (Sprint 38 W2).
2. `infrastructure/audit/event_log.py` → canonical home (services.io.indexers.log_indexer).
3. ADR-0286 narrow allowance verified — `infrastructure → services` allowed.
4. `core/observability/` is now PEP 420 namespace package (subpackages preserved).

Per ADR-0286 §3: narrow infrastructure → services allowance for `log_indexer`.
Per ADR-0282 §3 Phase B: prune 1 entry.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest


def test_core_observability_log_indexer_module_does_not_exist() -> None:
    """``core.observability.log_indexer`` proxy fully removed (Sprint 38 W2).

    Pre-fix: 27 LOC pure re-export proxy (LogIndexer, get_log_indexer).
    Post-fix: caller imports напрямую из `services.io.indexers.log_indexer`.
    """
    sys.modules.pop("src.backend.core.observability.log_indexer", None)

    with pytest.raises(ModuleNotFoundError) as exc_info:
        importlib.import_module("src.backend.core.observability.log_indexer")

    assert "log_indexer" in str(exc_info.value) or "observability/log_indexer" in str(
        exc_info.value
    )


def test_services_io_indexers_is_canonical_home() -> None:
    """``services.io.indexers.log_indexer.get_log_indexer`` is canonical."""
    from src.backend.services.io.indexers.log_indexer import LogIndexer, get_log_indexer

    assert callable(get_log_indexer)
    assert LogIndexer is not None


class TestCallerMigration:
    """Caller migration: 1 caller + 1 test mock."""

    def test_event_log_inline_imports_services_io(self) -> None:
        """`infrastructure/audit/event_log.py` (1 caller) inline-imports
        `get_log_indexer` напрямую из `services.io.indexers.log_indexer`.

        Sprint 38 W2: removed core.observability.log_indexer proxy → caller migrated.
        """
        text = Path("src/backend/infrastructure/audit/event_log.py").read_text(
            encoding="utf-8"
        )
        assert "from src.backend.services.io.indexers.log_indexer import" in text
        assert "from src.backend.core.observability.log_indexer import" not in text, (
            "infrastructure/audit/event_log.py не должна использовать "
            "core.observability.log_indexer proxy (Sprint 38 W2: proxy removed)"
        )


class TestADR0286Allowance:
    """ADR-0286 narrow allowance: infrastructure → services.X allowed."""

    def test_check_layers_matrix_includes_services_for_infrastructure(self) -> None:
        """ALLOWED map: infrastructure includes services per ADR-0286."""
        import re

        from tools.check_layers import ALLOWED  # type: ignore[import-not-found]

        assert "services" in ALLOWED.get("infrastructure", set()), (
            "ALLOWED matrix should include 'services' в infrastructure "
            "set (ADR-0286 narrow allowance)"
        )

    def test_layer_checker_passes_event_log_to_services_io(self) -> None:
        """`make layers` (or manual run) exits 0 после ADR-0286 update."""
        import subprocess

        result = subprocess.run(
            ["make", "layers"], capture_output=True, text=True, timeout=120
        )
        assert result.returncode == 0, (
            f"`make layers` should pass after ADR-0286 matrix update.\n"
            f"stderr: {result.stderr[-500:]}"
        )


class TestSiblingModulesPreserved:
    """`core/observability/` sibling modules (NOT touched by Sprint 38 W2)."""

    def test_other_observability_modules_intact(self) -> None:
        """Other `core.observability.*` modules preserved (NOT touched)."""
        from src.backend.core.observability.baggage import set_baggage
        from src.backend.core.observability.metrics import record_circuit_breaker_state

        assert callable(set_baggage)
        assert callable(record_circuit_breaker_state)
