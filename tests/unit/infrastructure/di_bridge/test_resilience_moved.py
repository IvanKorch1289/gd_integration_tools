"""Regression tests для resilience_bridge relocation (Sprint 40 W1 Item 4).

Покрывает:
1. `src/backend/infrastructure/di_bridge/resilience.py` exists (NOT
   `core/di/providers/resilience_bridge.py` — moved per Phase B Item 8).
2. `infrastructure_locator` imports 10 functions из new location.
3. `get_bulkhead_class` / `get_bulkhead_attr` / etc. still callable.
4. NO new layer violation (resilience_bridge moved to infrastructure layer).

Per ADR-0282 §3 Phase B Item 8: relocate \`core/di/providers/resilience_bridge.py\`
→ \`infrastructure/di_bridge/resilience.py\` (avoids core→infrastructure
layer violation). 4 entries off allowlist (Phase B ratchet acceleration).
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest


class TestResilienceBridgeMoved:
    """Verify resilience_bridge relocated to infrastructure layer."""

    def test_new_location_exists(self) -> None:
        """`src/backend/infrastructure/di_bridge/resilience.py` exists."""
        new_path = Path("src/backend/infrastructure/di_bridge/resilience.py")
        assert new_path.exists(), (
            f"Resilience bridge должен быть moved to {new_path} "
            f"(S40 W1 Item 4: relocate from core/ → infrastructure/)"
        )

    def test_old_location_removed(self) -> None:
        """`src/backend/core/di/providers/resilience_bridge.py` REMOVED."""
        old_path = Path("src/backend/core/di/providers/resilience_bridge.py")
        assert not old_path.exists(), (
            f"Old resilience_bridge path должен быть removed: {old_path}"
        )

    def test_new_location_importable(self) -> None:
        """New resilience module imports успешно."""
        sys.modules.pop(
            "src.backend.infrastructure.di_bridge.resilience", None
        )
        module = importlib.import_module(
            "src.backend.infrastructure.di_bridge.resilience"
        )
        assert hasattr(module, "get_bulkhead_class")
        assert hasattr(module, "get_bulkhead_attr")
        assert hasattr(module, "get_unified_rate_limiter_attr")

    def test_get_bulkhead_class_returns_callable(self) -> None:
        """get_bulkhead_class возвращает class (lazy-loaded)."""
        from src.backend.infrastructure.di_bridge.resilience import (
            get_bulkhead_class,
        )

        result = get_bulkhead_class()
        assert result is not None

    def test_get_bulkhead_attr_returns_attribute(self) -> None:
        """get_bulkhead_attr(\"Bulkhead\") возвращает class."""
        from src.backend.infrastructure.di_bridge.resilience import (
            get_bulkhead_attr,
        )

        result = get_bulkhead_attr("Bulkhead")
        assert result is not None


class TestInfrastructureLocatorMigrated:
    """Verify infrastructure_locator uses new resilience bridge location."""

    def test_locator_imports_from_new_path(self) -> None:
        """infrastructure_locator imports из new resilience location."""
        text = Path(
            "src/backend/core/di/providers/infrastructure_locator.py"
        ).read_text(encoding="utf-8")
        assert (
            "from src.backend.infrastructure.di_bridge.resilience import"
            in text
        ), (
            "infrastructure_locator должна import из new location "
            "(S40 W1 Item 4 migration)"
        )
        assert (
            "from src.backend.core.di.providers.resilience_bridge"
            not in text
        ), (
            "Old resilience_bridge import path НЕ должен быть в "
            "infrastructure_locator (S40 W1 Item 4 migration)"
        )

    def test_locator_bulkhead_class_callable(self) -> None:
        """infrastructure_locator.get_bulkhead_class returns class (via new path)."""
        from src.backend.core.di.providers.infrastructure_locator import (
            get_bulkhead_class,
        )

        result = get_bulkhead_class()
        assert result is not None


class TestAllowlistReduction:
    """Verify 4 allowlist entries removed (Phase B ratchet acceleration)."""

    def test_resilience_bridge_entries_removed(self) -> None:
        """4 resilience_bridge entries removed from allowlist."""
        text = Path("tools/check_layers_allowlist.txt").read_text(
            encoding="utf-8"
        )
        # Verify NO entries with `resilience_bridge` source path
        for line in text.splitlines():
            if line.startswith("#") or not line.strip():
                continue
            if "resilience_bridge" in line:
                assert False, (
                    f"resilience_bridge entry still in allowlist: {line}"
                )
