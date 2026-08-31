"""Regression tests для search_bridge + health_bridge relocation (Sprint 41 W1 Item 6).

Покрывает:
1. Both bridges relocated to infrastructure/di_bridge/.
2. infrastructure_locator imports из new locations.
3. Allowlist entries removed.
"""

from __future__ import annotations

from pathlib import Path

import pytest


class TestSearchBridgeMoved:
    """search_bridge → infrastructure/di_bridge/search.py."""

    def test_new_location_exists(self) -> None:
        """`src/backend/infrastructure/di_bridge/search.py` exists."""
        new_path = Path("src/backend/infrastructure/di_bridge/search.py")
        assert new_path.exists(), (
            f"Search bridge должен быть moved to {new_path} "
            f"(S41 W1 Item 6)"
        )

    def test_old_location_removed(self) -> None:
        """`src/backend/core/di/providers/search_bridge.py` REMOVED."""
        old_path = Path("src/backend/core/di/providers/search_bridge.py")
        assert not old_path.exists()

    def test_locator_imports_from_new_path(self) -> None:
        """infrastructure_locator imports из new search location."""
        text = Path(
            "src/backend/core/di/providers/infrastructure_locator.py"
        ).read_text(encoding="utf-8")
        assert (
            "from src.backend.infrastructure.di_bridge.search import"
            in text
        )
        assert (
            "from src.backend.core.di.providers.search_bridge"
            not in text
        )

    def test_search_bridge_entries_removed(self) -> None:
        """2 search_bridge entries removed from allowlist."""
        text = Path("tools/check_layers_allowlist.txt").read_text(
            encoding="utf-8"
        )
        for line in text.splitlines():
            if line.startswith("#") or not line.strip():
                continue
            if "search_bridge" in line:
                assert False, f"search_bridge entry still in allowlist: {line}"


class TestHealthBridgeMoved:
    """health_bridge → infrastructure/di_bridge/health.py."""

    def test_new_location_exists(self) -> None:
        """`src/backend/infrastructure/di_bridge/health.py` exists."""
        new_path = Path("src/backend/infrastructure/di_bridge/health.py")
        assert new_path.exists()

    def test_old_location_removed(self) -> None:
        """`src/backend/core/di/providers/health_bridge.py` REMOVED."""
        old_path = Path("src/backend/core/di/providers/health_bridge.py")
        assert not old_path.exists()

    def test_locator_imports_from_new_path(self) -> None:
        """infrastructure_locator imports из new health location."""
        text = Path(
            "src/backend/core/di/providers/infrastructure_locator.py"
        ).read_text(encoding="utf-8")
        assert (
            "from src.backend.infrastructure.di_bridge.health import"
            in text
        )
        assert (
            "from src.backend.core.di.providers.health_bridge"
            not in text
        )

    def test_health_bridge_entries_removed(self) -> None:
        """3 health_bridge entries removed from allowlist."""
        text = Path("tools/check_layers_allowlist.txt").read_text(
            encoding="utf-8"
        )
        for line in text.splitlines():
            if line.startswith("#") or not line.strip():
                continue
            if "health_bridge" in line:
                assert False, f"health_bridge entry still in allowlist: {line}"
