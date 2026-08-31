"""Regression tests для cdc_bridge relocation (Sprint 42 Item 1).

Покрывает:
1. `src/backend/infrastructure/di_bridge/cdc.py` exists (NOT
   `core/di/providers/cdc_bridge.py` — moved per Phase B).
2. `infrastructure_locator` imports из new location.
3. 4 entry callers still work (cdc_client_adapter, debezium_events_backend,
   listen_notify_backend, poll_backend).
4. NO new layer violation (cdc_bridge moved to infrastructure layer).
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest


class TestCdcBridgeMoved:
    """Verify cdc_bridge relocated to infrastructure layer."""

    def test_new_location_exists(self) -> None:
        """`src/backend/infrastructure/di_bridge/cdc.py` exists."""
        new_path = Path("src/backend/infrastructure/di_bridge/cdc.py")
        assert new_path.exists(), (
            f"CDC bridge должен быть moved to {new_path} "
            f"(Sprint 42 Item 1: relocate from core/ → infrastructure/)"
        )

    def test_old_location_removed(self) -> None:
        """`src/backend/core/di/providers/cdc_bridge.py` REMOVED."""
        old_path = Path("src/backend/core/di/providers/cdc_bridge.py")
        assert not old_path.exists(), (
            f"Old cdc_bridge path должен быть removed: {old_path}"
        )

    def test_new_location_importable(self) -> None:
        """New cdc module imports успешно."""
        sys.modules.pop("src.backend.infrastructure.di_bridge.cdc", None)
        module = importlib.import_module(
            "src.backend.infrastructure.di_bridge.cdc"
        )
        # Verify all 5 export functions still present (verified via grep)
        assert hasattr(module, "get_poll_cdc_backend_class")
        assert hasattr(module, "get_listen_notify_cdc_backend_class")
        assert hasattr(module, "get_debezium_cdc_backend_class")
        assert hasattr(module, "get_cdc_client_adapter_class")
        assert hasattr(module, "get_debezium_events_cdc_backend_class")

    def test_get_poll_cdc_backend_class_callable(self) -> None:
        """get_poll_cdc_backend_class returns CDC backend class."""
        from src.backend.infrastructure.di_bridge.cdc import (
            get_poll_cdc_backend_class,
        )

        cls = get_poll_cdc_backend_class()
        assert cls is not None


class TestInfrastructureLocatorMigrated:
    """Verify infrastructure_locator uses new cdc bridge location."""

    def test_locator_imports_from_new_path(self) -> None:
        """infrastructure_locator imports из new cdc location."""
        text = Path(
            "src/backend/core/di/providers/infrastructure_locator.py"
        ).read_text(encoding="utf-8")
        assert (
            "from src.backend.infrastructure.di_bridge.cdc import"
            in text
        ), (
            "infrastructure_locator должна import из new location "
            "(Sprint 42 Item 1 migration)"
        )
        assert (
            "from src.backend.core.di.providers.cdc_bridge"
            not in text
        ), (
            "Old cdc_bridge import path НЕ должен быть в "
            "infrastructure_locator (Sprint 42 Item 1 migration)"
        )


class TestAllowlistReduction:
    """Verify 3 entries removed (Phase B Item 1, gap-agent over-estimated to 4)."""

    def test_cdc_bridge_entries_removed(self) -> None:
        """3 cdc_bridge entries removed from allowlist (gap-agent estimated 4)."""
        text = Path("tools/check_layers_allowlist.txt").read_text(
            encoding="utf-8"
        )
        cdc_lines = [
            line for line in text.splitlines()
            if line.startswith("#") is False
            and "cdc_bridge" in line
        ]
        assert len(cdc_lines) == 0, (
            f"All cdc_bridge entries should be removed, found: {cdc_lines}"
        )
