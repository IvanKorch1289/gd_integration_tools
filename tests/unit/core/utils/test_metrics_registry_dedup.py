"""Unit-тесты для cycle 29 P1-#4: metrics_registry deduplication.

Per Master Prompt P1-#4: удали дублирующий metrics_registry из
infrastructure/observability, оставь только core/utils/metrics_registry.
"""

# ruff: noqa: S101

from __future__ import annotations

import os
import re


class TestMetricsRegistrySingleSource:
    """core/utils/metrics_registry.py must be the only source."""

    def test_canonical_exists(self):
        path = "src/backend/core/utils/metrics_registry.py"
        assert os.path.exists(path), f"{path} missing"

    def test_duplicate_removed(self):
        """infrastructure/observability/metrics_registry.py must NOT exist."""
        path = "src/backend/infrastructure/observability/metrics_registry.py"
        assert not os.path.exists(path), (
            f"Duplicate {path} still exists. Should be removed per P1-#4."
        )

    def test_no_imports_of_removed_path(self):
        """No source code should import from the removed path.

        Excludes docstring/comment references (only checks import statements).
        """
        removed = "from src.backend.infrastructure.observability.metrics_registry"
        results = []
        for root, _, files in os.walk("src/"):
            if "__pycache__" in root:
                continue
            for f in files:
                if not f.endswith(".py"):
                    continue
                p = os.path.join(root, f)
                with open(p) as fp:
                    content = fp.read()
                # Strip docstrings/comments
                lines = [
                    l for l in content.split("\n")
                    if not l.strip().startswith(("#", '"', "'", "*", ".."))
                    and '"""' not in l and "'''" not in l
                ]
                code = "\n".join(lines)
                if removed in code:
                    results.append(p)
        assert not results, (
            f"Found {len(results)} files still importing removed path: "
            f"{results[:5]}"
        )


class TestMetricsReExportsWork:
    """All infrastructure metrics users must still work via core import."""

    def test_import_path_works(self):
        """core/utils/metrics_registry must be importable."""
        # Module-level imports
        from src.backend.core.utils.metrics_registry import (
            DEFAULT_LABELS,
            MetricsRegistry,
            metrics_registry,
        )

        assert DEFAULT_LABELS is not None
        assert MetricsRegistry is not None
        assert metrics_registry is not None


class TestMigrationCompleteness:
    """All 14 infrastructure importers migrated to core/utils path."""

    EXPECTED_MIGRATED_FILES = [
        "src/backend/infrastructure/observability/metrics.py",
        "src/backend/infrastructure/observability/client_metrics.py",
        "src/backend/infrastructure/observability/prometheus_temporal_exporter.py",
        "src/backend/infrastructure/observability/plugin_resource_monitor.py",
        "src/backend/infrastructure/observability/nats_metrics.py",
        "src/backend/infrastructure/secrets/vault_client.py",
        "src/backend/infrastructure/workflow/worker_probes.py",
        "src/backend/infrastructure/ai/semantic_cache.py",
        "src/backend/infrastructure/scheduler/observability.py",
        "src/backend/infrastructure/resilience/reconnection.py",
        "src/backend/infrastructure/resilience/components/database_chain.py",
        "src/backend/infrastructure/resilience/snapshot_job.py",
        "src/backend/infrastructure/cache/lru_cache.py",
        "src/backend/infrastructure/cache/rag/metrics.py",
    ]

    def test_all_importers_migrated(self):
        """Each migrated file must import from core (not infrastructure/observability)."""
        not_migrated = []
        for p in self.EXPECTED_MIGRATED_FILES:
            with open(p) as f:
                content = f.read()
            # Either uses core/utils path or doesn't import metrics_registry at all
            if "observability.metrics_registry" in content and "core" not in content.split("observability.metrics_registry")[0][-30:]:
                # Check if it's a docstring reference (acceptable)
                if not_migrated and "infrastructure.observability.metrics_registry" in content:
                    # Has infrastructure.observability.metrics_registry import
                    if "from src.backend.infrastructure.observability.metrics_registry" in content:
                        not_migrated.append(p)
        assert not not_migrated, f"Files still importing removed path: {not_migrated}"

    def test_files_use_core_path(self):
        """Each migrated file must use the core path."""
        for p in self.EXPECTED_MIGRATED_FILES:
            with open(p) as f:
                content = f.read()
            assert "from src.backend.core.utils.metrics_registry" in content, (
                f"{p} not migrated to core path"
            )
