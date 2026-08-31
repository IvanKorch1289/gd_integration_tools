"""Regression tests для observability_bridge relocation (Sprint 41 W1 Item 3).

Покрывает:
1. `src/backend/infrastructure/di_bridge/observability.py` exists (NOT
   `core/di/providers/observability_bridge.py` — moved per Phase B).
2. `infrastructure_locator` imports из new location.
3. 13 exports (get_*, metrics_registry, etc.) still callable.
4. NO new layer violation (observability_bridge moved to infrastructure layer).
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest


class TestObservabilityBridgeMoved:
    """Verify observability_bridge relocated to infrastructure layer."""

    def test_new_location_exists(self) -> None:
        """`src/backend/infrastructure/di_bridge/observability.py` exists."""
        new_path = Path("src/backend/infrastructure/di_bridge/observability.py")
        assert new_path.exists(), (
            f"Observability bridge должен быть moved to {new_path} "
            f"(S41 W1 Item 3: relocate from core/ → infrastructure/)"
        )

    def test_old_location_removed(self) -> None:
        """`src/backend/core/di/providers/observability_bridge.py` REMOVED."""
        old_path = Path("src/backend/core/di/providers/observability_bridge.py")
        assert not old_path.exists(), (
            f"Old observability_bridge path должен быть removed: {old_path}"
        )

    def test_new_location_importable(self) -> None:
        """New observability module imports успешно."""
        sys.modules.pop(
            "src.backend.infrastructure.di_bridge.observability", None
        )
        module = importlib.import_module(
            "src.backend.infrastructure.di_bridge.observability"
        )
        # Verify exports still present
        assert hasattr(module, "get_correlation_id")
        assert hasattr(module, "get_metrics_registry_class")
        assert hasattr(module, "get_logger_factory")

    def test_get_correlation_id_callable(self) -> None:
        """get_correlation_id is callable (lazy-resolved)."""
        from src.backend.infrastructure.di_bridge.observability import (
            get_correlation_id,
        )

        assert callable(get_correlation_id)

    def test_get_metrics_registry_class_callable(self) -> None:
        """get_metrics_registry_class returns class."""
        from src.backend.infrastructure.di_bridge.observability import (
            get_metrics_registry_class,
        )

        cls = get_metrics_registry_class()
        assert cls is not None


class TestInfrastructureLocatorMigrated:
    """Verify infrastructure_locator uses new observability bridge location."""

    def test_locator_imports_from_new_path(self) -> None:
        """infrastructure_locator imports из new observability location."""
        text = Path(
            "src/backend/core/di/providers/infrastructure_locator.py"
        ).read_text(encoding="utf-8")
        assert (
            "from src.backend.infrastructure.di_bridge.observability import"
            in text
        ), (
            "infrastructure_locator должна import из new location "
            "(S41 W1 Item 3 migration)"
        )
        assert (
            "from src.backend.core.di.providers.observability_bridge"
            not in text
        ), (
            "Old observability_bridge import path НЕ должен быть в "
            "infrastructure_locator (S41 W1 Item 3 migration)"
        )


class TestAllowlistReduction:
    """Verify 4 allowlist entries removed (Phase B ratchet acceleration)."""

    def test_observability_bridge_entries_removed(self) -> None:
        """4 observability_bridge entries removed from allowlist."""
        text = Path("tools/check_layers_allowlist.txt").read_text(
            encoding="utf-8"
        )
        # Verify NO entries with `observability_bridge` source path
        for line in text.splitlines():
            if line.startswith("#") or not line.strip():
                continue
            if "observability_bridge" in line:
                assert False, (
                    f"observability_bridge entry still in allowlist: {line}"
                )
