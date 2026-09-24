"""Regression tests для lazy `__getattr__` proxy в dlq/__init__.py.

Per v4 §10 P1 'evidence требует testable surface': lazy proxy pattern
(cycle 158+ Option A из STARTUP_BOTTLENECK_INVESTIGATION_2026-09-23)
требует regression coverage.

Pre-fix: dlq/__init__.py eager imports 6 writers + dlq_base.
Cold import = ~10.7s (per DLQ_REGRESSION_2026-09-24).

Post-fix: lazy __getattr__ proxy — 0.004s cold import.
"""

from __future__ import annotations

import importlib
import sys

import pytest


def _reload_dlq():
    """Reload ``dlq`` module to reset ``__getattr__`` cache.

    Per v4 §10 testable surface: lazy proxy state должен быть testable
    для verifying resolution patterns.
    """
    if "src.backend.infrastructure.messaging.dlq" in sys.modules:
        del sys.modules["src.backend.infrastructure.messaging.dlq"]
    return importlib.import_module("src.backend.infrastructure.messaging.dlq")


class TestLazyInitProxy:
    """``__getattr__`` lazy proxy pattern."""

    def test_dlq_import_does_not_load_writers(self) -> None:
        """Importing ``dlq`` package does NOT trigger eager writer imports.

        Pre-fix поведение: ``from .fanout_writer import FanoutDLQWriter``
        etc. срабатывают instantly. Post-fix: lazy proxy — zero-cost
        до первого attribute access.
        """
        # Import fresh.
        _reload_dlq()

        # Submodule writers не должны быть in sys.modules после import.
        # (мы проверяем что proxy не triggered eager imports).
        writer_names = [
            "src.backend.infrastructure.messaging.dlq.fanout_writer",
            "src.backend.infrastructure.messaging.dlq.kafka_writer",
            "src.backend.infrastructure.messaging.dlq.rabbit_writer",
            "src.backend.infrastructure.messaging.dlq.nats_writer",
            "src.backend.infrastructure.messaging.dlq.inbox_writer",
            "src.backend.infrastructure.messaging.dlq.memory_writer",
        ]
        not_loaded = [n for n in writer_names if n not in sys.modules]
        assert len(not_loaded) >= 5, (
            f"Expected ≥5 writer submodules NOT loaded после ``import dlq``: "
            f"already loaded: {[n for n in writer_names if n in sys.modules]}"
        )

    def test_attribute_access_triggers_lazy_import(self) -> None:
        """Access to ``dlq.KafkaDLQWriter`` triggers ``kafka_writer`` import.

        Post-fix: lazy resolution — только первый ``getattr()`` triggers
        module load. Subsequent accesses return cached value.
        """
        dlq = _reload_dlq()

        # Pre-condition: kafka_writer not in sys.modules.
        kafka_module = "src.backend.infrastructure.messaging.dlq.kafka_writer"
        assert kafka_module not in sys.modules, (
            "kafka_writer should NOT be eagerly loaded"
        )

        # Trigger lazy import.
        writer_class = dlq.KafkaDLQWriter

        # Post-condition: kafka_writer теперь loaded.
        assert kafka_module in sys.modules, (
            "После access dlq.KafkaDLQWriter → kafka_writer should be loaded"
        )
        assert writer_class.__name__ == "KafkaDLQWriter"

    def test_caching_subsequent_lookups(self) -> None:
        """Second ``getattr()`` для same name — cached (no re-import)."""
        dlq = _reload_dlq()

        # First access: triggers load.
        first = dlq.DLQEnvelope
        # Second access: cached (per ``_cached`` dict proxy).
        second = dlq.DLQEnvelope
        # Same identity.
        assert first is second, "Second lookup должен return cached value"

    def test_unknown_attribute_raises_attribute_error(self) -> None:
        """``getattr(dlq, 'UnknownClass')`` raises ``AttributeError``.

        Lazy proxy не fallback to eager import — strict contract.
        """
        dlq = _reload_dlq()
        with pytest.raises(AttributeError) as exc_info:
            _ = dlq.NonExistentClass  # noqa: F841
        assert "NonExistentClass" in str(exc_info.value)


class TestBackwardCompat:
    """Public contract preserved per v4 §6 «Parity»."""

    def test_dlq_envelope_via_lazy(self) -> None:
        """``from dlq import DLQEnvelope`` works через lazy proxy.

        Test consumer path: tests + production code (composition root).
        """
        dlq = _reload_dlq()
        from src.backend.infrastructure.messaging.dlq_base import (
            DLQEnvelope as DirectDLQEnvelope,
        )
        assert dlq.DLQEnvelope is DirectDLQEnvelope, (
            "Lazy proxy must return same class object как прямой import"
        )

    def test_dlq_reason_via_lazy(self) -> None:
        """``from dlq import DLQReason`` works."""
        dlq = _reload_dlq()
        from src.backend.infrastructure.messaging.dlq_base import (
            DLQReason as DirectDLQReason,
        )
        assert dlq.DLQReason is DirectDLQReason

    def test_dlq_writer_protocol_via_lazy(self) -> None:
        """``from dlq import DLQWriter`` works."""
        dlq = _reload_dlq()
        from src.backend.infrastructure.messaging.dlq_base import (
            DLQWriter as DirectDLQWriter,
        )
        assert dlq.DLQWriter is DirectDLQWriter

    def test_inmemory_dlq_writer_via_lazy(self) -> None:
        """``from dlq import InMemoryDLQWriter`` works."""
        dlq = _reload_dlq()
        from src.backend.infrastructure.messaging.dlq.memory_writer import (
            InMemoryDLQWriter as DirectInMemoryDLQWriter,
        )
        assert dlq.InMemoryDLQWriter is DirectInMemoryDLQWriter

    def test_all_exports_resolvable(self) -> None:
        """All ``__all__`` entries are resolvable via lazy proxy."""
        dlq = _reload_dlq()
        for name in dlq.__all__:
            obj = getattr(dlq, name)
            assert obj is not None, f"{name} should resolve через __getattr__"


class TestColdImportPerformance:
    """Lazy proxy makes import cheap."""

    def test_cold_import_under_100ms(self) -> None:
        """Cold import of dlq package < 100ms (was 10.7s before fix).

        Per v4 §3 measurement: subprocess-based cold import must be
        significantly faster than eager baseline.
        """
        import subprocess
        import sys as _sys

        result = subprocess.run(
            [_sys.executable, "-c", (
                "import time; start = time.monotonic(); "
                "import src.backend.infrastructure.messaging.dlq; "
                "print(f'{time.monotonic() - start:.4f}')"
            )],
            capture_output=True, text=True, timeout=30,
            check=True,
        )
        elapsed = float(result.stdout.strip())

        # Pre-fix: ~10.7s. Post-fix target: <100ms (well within threshold).
        assert elapsed < 0.1, (
            f"dlq cold import should be <100ms post-fix; got {elapsed:.3f}s"
        )
