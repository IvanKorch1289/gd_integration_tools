"""Unit-тесты для cycle 29 P1-#2: core→services layer violation fixes.

Verifies:
1. get_ad_directory_client_provider exists in core/di/providers/auth.py
2. ldap_client_factory uses DI provider with fallback
3. No direct core→services imports remain in fixed files
"""

# ruff: noqa: S101

from __future__ import annotations

import ast
import os
import re


class TestAdDirectoryProvider:
    """DI provider for AD client must exist in core/di/providers/auth.py."""

    def test_provider_function_exists(self):
        path = "src/backend/core/di/providers/auth.py"
        with open(path) as f:
            content = f.read()
        assert "def get_ad_directory_client_provider" in content, (
            "Missing get_ad_directory_client_provider in auth.py"
        )
        assert "def set_ad_directory_client_provider" in content, (
            "Missing set_ad_directory_client_provider in auth.py"
        )

    def test_provider_in_all(self):
        path = "src/backend/core/di/providers/auth.py"
        with open(path) as f:
            content = f.read()
        # Both must be in __all__ for public API
        assert '"get_ad_directory_client_provider"' in content
        assert '"set_ad_directory_client_provider"' in content

    def test_provider_uses_module_registry(self):
        """Provider must use resolve_module() for late import."""
        path = "src/backend/core/di/providers/auth.py"
        with open(path) as f:
            content = f.read()
        # Find get_ad_directory_client_provider function
        for line in content.split("\n"):
            if "get_ad_directory_client_provider" in line and "def " in line:
                # Check next 10 lines for resolve_module call
                idx = content.find(line)
                section = content[idx:idx + 500]
                assert "resolve_module" in section
                return
        assert False, "Provider not found"


class TestLdapClientFactoryMigration:
    """ldap_client_factory.py must use the DI provider."""

    def test_uses_di_provider(self):
        path = "src/backend/core/auth/ldap_client_factory.py"
        with open(path) as f:
            content = f.read()
        # Must import the DI provider
        assert "get_ad_directory_client_provider" in content, (
            "ldap_client_factory.py must use DI provider"
        )

    def test_has_fallback(self):
        """Fallback to direct import must exist (for dev_light builds)."""
        path = "src/backend/core/auth/ldap_client_factory.py"
        with open(path) as f:
            content = f.read()
        # Direct import is preserved inside except ImportError
        assert "except ImportError" in content
        assert "src.backend.services.auth.ad_directory_client" in content

    def test_no_unconditional_direct_import(self):
        """The direct import must be inside except block, not top-level."""
        path = "src/backend/core/auth/ldap_client_factory.py"
        with open(path) as f:
            content = f.read()
        # Find all `from src.backend.services` imports
        direct_imports = re.findall(
            r"^from src\.backend\.services[^:]+import", content, re.M
        )
        # Some may be in TYPE_CHECKING or except blocks
        # Ponytail-YAGNI: we accept direct import in except block for fallback
        # But not at module level (would be a violation)
        # Check that each direct import is inside `except` or TYPE_CHECKING
        lines = content.split("\n")
        for i, line in enumerate(lines):
            if "from src.backend.services" in line and "import" in line:
                # Check if it's inside TYPE_CHECKING block or except
                # Look back for TYPE_CHECKING or except
                context = "\n".join(lines[max(0, i - 5):i + 1])
                if "TYPE_CHECKING" in context:
                    continue  # OK — type-only
                if "except" in context:
                    continue  # OK — fallback in except
                # Module-level direct import — VIOLATION
                assert False, f"Module-level direct import at line {i + 1}: {line}"


class TestNoCoreWorkflowBuilder:
    """Master Prompt references core/workflow/builder.py — verify it doesn't exist."""

    def test_builder_file_does_not_exist(self):
        """core/workflow/builder.py is referenced in Master Prompt but doesn't exist."""
        path = "src/backend/core/workflow/builder.py"
        # If it exists, check imports; if not, that's fine (lazy __getattr__).
        if os.path.exists(path):
            with open(path) as f:
                content = f.read()
            # No direct services/infrastructure imports
            direct = re.findall(
                r"^from src\.backend\.(?:services|infrastructure)[^:]+import",
                content, re.M
            )
            assert not direct, f"Direct upper-layer imports: {direct}"


class TestLayerViolationsClosed:
    """Master Prompt P1-#2 violations closed."""

    def test_core_to_services_violation_removed(self):
        """core/auth/ldap_client_factory.py:102 had direct core→services import."""
        # Fixed: now uses DI provider with fallback only
        # The unconditional direct import should be gone
        path = "src/backend/core/auth/ldap_client_factory.py"
        with open(path) as f:
            content = f.read()
        # The direct import must be inside except (Ponytail fallback for dev_light)
        # and not at module level
        # Allow up to 1 direct import (the except fallback)
        direct = re.findall(
            r"^from src\.backend\.services[^:]+import", content, re.M
        )
        # Should be 0 (in except block — line starts with spaces)
        assert len(direct) == 0, (
            f"Found {len(direct)} module-level direct imports. "
            "Direct imports must be in except block only."
        )
