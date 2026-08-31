"""Regression tests для dlq_bridge relocation (Sprint 42 Item 2).

Покрывает:
1. `src/backend/infrastructure/di_bridge/dlq.py` exists.
2. `infrastructure_locator` imports из new location.
3. `pii_erase.py` (the SECOND caller) imports из new location.
4. 2 entries removed from allowlist.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest


class TestDlqBridgeMoved:
    """Verify dlq_bridge relocated to infrastructure layer."""

    def test_new_location_exists(self) -> None:
        """`src/backend/infrastructure/di_bridge/dlq.py` exists."""
        new_path = Path("src/backend/infrastructure/di_bridge/dlq.py")
        assert new_path.exists(), (
            f"DLQ bridge должен быть moved to {new_path} "
            f"(Sprint 42 Item 2: relocate from core/ → infrastructure/)"
        )

    def test_old_location_removed(self) -> None:
        """`src/backend/core/di/providers/dlq_bridge.py` REMOVED."""
        old_path = Path("src/backend/core/di/providers/dlq_bridge.py")
        assert not old_path.exists()

    def test_new_location_importable(self) -> None:
        """New dlq module imports successfully."""
        sys.modules.pop("src.backend.infrastructure.di_bridge.dlq", None)
        module = importlib.import_module(
            "src.backend.infrastructure.di_bridge.dlq"
        )
        # Verify exports still present
        assert hasattr(module, "get_dlq_envelope_class")
        assert hasattr(module, "get_dlq_reason_class")

    def test_get_dlq_envelope_class_callable(self) -> None:
        """get_dlq_envelope_class returns DLQ envelope class."""
        from src.backend.infrastructure.di_bridge.dlq import (
            get_dlq_envelope_class,
        )

        cls = get_dlq_envelope_class()
        assert cls is not None


class TestInfrastructureLocatorMigrated:
    """Verify infrastructure_locator uses new dlq bridge location."""

    def test_locator_imports_from_new_path(self) -> None:
        """infrastructure_locator imports из new dlq location."""
        text = Path(
            "src/backend/core/di/providers/infrastructure_locator.py"
        ).read_text(encoding="utf-8")
        assert (
            "from src.backend.infrastructure.di_bridge.dlq import"
            in text
        ), (
            "infrastructure_locator должна import из new location "
            "(Sprint 42 Item 2 migration)"
        )
        assert (
            "from src.backend.core.di.providers.dlq_bridge"
            not in text
        )


class TestPiiEraseMigrated:
    """Verify pii_erase.py (the SECOND caller) uses new dlq location."""

    def test_pii_erase_imports_from_new_path(self) -> None:
        """`src/backend/dsl/engine/processors/security/pii_erase.py` (caller) imports из new dlq location."""
        text = Path(
            "src/backend/dsl/engine/processors/security/pii_erase.py"
        ).read_text(encoding="utf-8")
        assert (
            "from src.backend.infrastructure.di_bridge.dlq import"
            in text
        ), (
            "pii_erase.py должна import из new dlq location "
            "(Sprint 42 Item 2 migration)"
        )
        assert (
            "from src.backend.core.di.providers.dlq_bridge"
            not in text
        )


class TestAllowlistReduction:
    """Verify 2 entries removed from allowlist."""

    def test_dlq_bridge_entries_removed(self) -> None:
        """2 dlq_bridge entries removed from allowlist."""
        text = Path("tools/check_layers_allowlist.txt").read_text(
            encoding="utf-8"
        )
        dlq_lines = [
            line for line in text.splitlines()
            if line.startswith("#") is False
            and "dlq_bridge" in line
        ]
        assert len(dlq_lines) == 0, (
            f"All dlq_bridge entries should be removed, found: {dlq_lines}"
        )
