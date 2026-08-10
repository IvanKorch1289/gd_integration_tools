"""Tests for tools/checks/check_routebuilder_mro.py (Layer 3 MRO gate).

Verifies:
- get_route_builder_mro returns the actual MRO from RouteBuilder class
- check_mro_depth passes when MRO depth <= max
- check_mro_depth fails when MRO depth > max
- filter_top_level_bases skips nested base classes
- CLI --info mode prints breakdown without failing
"""

from __future__ import annotations

import subprocess
import sys
from typing import Protocol


class TestCheckMroDepth:
    """check_mro_depth function: budget enforcement."""

    def test_passes_when_within_budget(self) -> None:
        from tools.checks.check_routebuilder_mro import check_mro_depth

        # Current MRO is 82 — pass with budget=100, fail with budget=50.
        passed, msg = check_mro_depth(max_mro_depth=100)
        assert passed is True
        assert "OK" in msg
        assert "100" in msg

    def test_fails_when_over_budget(self) -> None:
        from tools.checks.check_routebuilder_mro import check_mro_depth

        passed, msg = check_mro_depth(max_mro_depth=50)
        assert passed is False
        assert "FAIL" in msg
        assert "exceeds budget" in msg

    def test_message_includes_actual_and_top_level_count(self) -> None:
        from tools.checks.check_routebuilder_mro import check_mro_depth

        passed, msg = check_mro_depth(max_mro_depth=50)
        assert passed is False
        assert "RouteBuilder MRO depth: 82" in msg
        assert "Top-level mixin bases: 78" in msg


class TestGetRouteBuilderMro:
    """get_route_builder_mro: returns actual MRO from RouteBuilder class."""

    def test_returns_non_empty_mro(self) -> None:
        from tools.checks.check_routebuilder_mro import get_route_builder_mro

        mro = get_route_builder_mro()
        assert len(mro) > 0
        assert mro[0].__name__ == "RouteBuilder"
        assert mro[-1] is object  # all classes inherit from object

    def test_mro_count_matches_class_method(self) -> None:
        """MRO from helper must match RouteBuilder.__mro__."""
        from src.backend.dsl.builder import RouteBuilder
        from tools.checks.check_routebuilder_mro import get_route_builder_mro

        assert get_route_builder_mro() == RouteBuilder.__mro__


class TestFilterTopLevelBases:
    """filter_top_level_bases: skip nested _XxxBase classes and protocols."""

    def test_skips_nested_base_classes(self) -> None:
        from tools.checks.check_routebuilder_mro import filter_top_level_bases

        # Synthetic MRO to verify the filter.
        class _XxxBase:
            pass

        class TopLevelMixin:
            pass

        class NestedProtocol(Protocol):
            pass

        class _PrivateInternal:
            pass

        class object_like:
            pass

        synthetic = (
            TopLevelMixin,
            _XxxBase,  # skipped (ends with Base)
            NestedProtocol,  # skipped (ends with Protocol)
            _PrivateInternal,  # skipped (starts with _)
            object_like,
        )
        filtered = filter_top_level_bases(synthetic)
        # _XxxBase, NestedProtocol, _PrivateInternal filtered out.
        # object_like not filtered by suffix but is not object itself —
        # check the filter excludes only matching classes.
        assert TopLevelMixin in filtered
        assert _XxxBase not in filtered
        assert NestedProtocol not in filtered
        assert _PrivateInternal not in filtered


class TestCLIMain:
    """CLI integration: tool runs end-to-end via subprocess."""

    def test_cli_default_fails(self) -> None:
        """Default budget (50) fails because current MRO is 82."""
        result = subprocess.run(
            [sys.executable, "tools/checks/check_routebuilder_mro.py"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 1
        assert "FAIL" in result.stdout
        assert "82" in result.stdout

    def test_cli_max_100_passes(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                "tools/checks/check_routebuilder_mro.py",
                "--max",
                "100",
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "OK" in result.stdout

    def test_cli_info_prints_breakdown(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                "tools/checks/check_routebuilder_mro.py",
                "--info",
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "RouteBuilder.__mro__" in result.stdout
        assert "82 classes" in result.stdout
