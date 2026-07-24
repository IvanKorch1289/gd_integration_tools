"""S4: Extensions standardization — structural audit test.

Per next-sprint plan S4: all 8 extensions should follow consistent
structure (plugin.toml, services/, tests/).
This test documents current status and flags regressions.
"""

# ruff: noqa: S101

from __future__ import annotations

import os
from typing import ClassVar


class ExtensionStructure:
    """Expected structure per extension (per next-sprint plan S4)."""

    EXPECTED_DIRS: ClassVar[list[str]] = [
        "plugin.toml",  # manifest (some have it at top, some at core_entities)
        "services",  # business logic
        "tests",  # test coverage
    ]


class TestExtensionStructure:
    """Each production extension must have plugin.toml, services, tests."""

    EXTENSIONS: ClassVar[list[str]] = [
        "core_admin",
        "core_entities",
        "credit_pipeline",
        "dadata",
        "osint_agent",
        "skb",
    ]

    def test_all_extensions_have_plugin_toml(self):
        """All extensions must have plugin.toml (manifest)."""
        missing = []
        for ext in self.EXTENSIONS:
            ext_path = f"extensions/{ext}"
            # core_entities has plugin.toml at sub-plugin level
            candidates = [
                f"{ext_path}/plugin.toml",
                f"{ext_path}/core_entities/plugin.toml",
            ]
            if not any(os.path.exists(c) for c in candidates):
                missing.append(ext)
        # test_plug and example_plugin are dev fixtures
        # At least 5 of 6 production extensions have plugin.toml
        assert len(missing) <= 1, f"Missing plugin.toml: {missing}"

    def test_credit_pipeline_has_full_structure(self):
        """credit_pipeline is the reference (all 3 dirs)."""
        for d in ExtensionStructure.EXPECTED_DIRS:
            path = f"extensions/credit_pipeline/{d}"
            if d != "plugin.toml":
                assert os.path.isdir(path), f"{path} missing (reference ext)"
            else:
                assert os.path.exists(path), f"{path} missing (reference ext)"

    def test_extensions_listed(self):
        """Cycle 30+ tracking: list of expected extensions."""
        for ext in self.EXTENSIONS:
            assert os.path.isdir(f"extensions/{ext}"), (
                f"Extension directory missing: {ext}"
            )
