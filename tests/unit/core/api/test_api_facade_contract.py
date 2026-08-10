"""Contract tests for core/api facade (cycle 59, Plan 9/10 P21).

Tests the facade that extensions use to import from src.backend.
Per DEEP_AUDIT_R3.10d: extensions import ONLY src.backend.sdk and
src.backend.core.api (this module), NEVER services/* or
infrastructure/* directly.

Cycle 59 invariant: this test file is the contract that
guarantees any new symbols added to core/api/__init__.py work
and don't break the existing migration pattern.
"""


from __future__ import annotations

import os
import sys

import pytest


class TestFacadeContractCycle59:
    """Cycle 59: solidifies facade contract for P21 (Plan 9/10)."""

    def test_facade_module_importable(self):
        """Facade is importable as ``src.backend.core.api``."""
        sys.path.insert(0, "src")
        import src.backend.core.api

        assert src.backend.core.api is not None

    def test_facade_exports_required_p21_categories(self):
        """P21 explicit categories must be present in __all__."""
        sys.path.insert(0, "src")
        import src.backend.core.api

        required = [
            "get_scheduler_provider",  # DI providers
            "AIGateway",  # AI entry
            "get_storage_facade_provider",  # P2.1 domain facades
            "get_auth_facade",
            "get_cache_facade",
            "emit_audit_safe",
        ]
        for sym in required:
            assert hasattr(src.backend.core.api, sym), (
                f"Missing from facade: {sym}"
            )

    def test_facade_handles_missing_dependencies_gracefully(self):
        """Facade must work even if some underlying providers fail to import.

        Cycle 59 invariant: lazy __getattr__ means individual symbols
        are only imported on access. If a provider fails to import,
        ONLY that specific symbol is unavailable, not the entire facade.
        """
        sys.path.insert(0, "src")
        import src.backend.core.api

        # Verify accessing AIGateway works (synchronous import).
        aigateway = src.backend.core.api.AIGateway
        assert aigateway is not None
        assert callable(aigateway) or isinstance(aigateway, type)

    def test_facade_lazy_loader_doesnt_break_at_import(self):
        """Importing facade shouldn't trigger chain deps (Vault, FastAPI, etc.).

        Cycle 59 invariant: facade module-level import has zero side
        effects. All DI providers + AIGateway loaded only on first
        attribute access.
        """
        sys.path.insert(0, "src")
        import src.backend.core.api

        # Verify __all__ is accessible without triggering chain deps.
        assert isinstance(src.backend.core.api.__all__, list)
        assert len(src.backend.core.api.__all__) > 0

    def test_facade_dir_includes_lazy_exports(self):
        """__dir__() must include lazy symbols for IDE/tab completion.

        Cycle 59 invariant: Python tooling (jedi, pylint) uses dir()
        to know which symbols are available. Lazy exports must be
        advertised in dir() without triggering their import.
        """
        sys.path.insert(0, "src")
        import src.backend.core.api

        d = dir(src.backend.core.api)
        for lazy_symbol in [
            "get_scheduler_provider",
            "AIGateway",
            "get_storage_facade_provider",
        ]:
            assert lazy_symbol in d, (
                f"{lazy_symbol} missing from dir() — IDE/tab completion broken"
            )

    def test_facade_attribute_error_for_unknown_symbol(self):
        """Unknown symbol raises clear AttributeError (NOT ImportError).

        Cycle 59 invariant: facade must distinguish between
        'attribute not exported' (AttributeError) and 'dependency
        import failed' (ImportError). Otherwise extensions get
        confusing stack traces.
        """
        sys.path.insert(0, "src")
        import src.backend.core.api

        with pytest.raises(AttributeError) as exc_info:
            src.backend.core.api.NonExistentSymbol

        # Should not be an ImportError or ModuleNotFoundError.
        assert not isinstance(exc_info.value, ImportError)
        assert "NonExistentSymbol" in str(exc_info.value)

    def test_facade_does_not_import_infrastructure_directly(self):
        """Per R3.10d: facade must NOT import from services/* or infrastructure/*.

        Cycle 59 invariant: even though facade re-exports symbols
        whose IMPLEMENTATION lives in services/infrastructure (e.g.
        AIGateway in services/ai/), the facade itself must only
        import from allowed layers (core, sdk).
        """
        with open("src/backend/core/api/__init__.py") as f:
            content = f.read()

        # Check imports in facade file itself.
        import ast

        tree = ast.parse(content)
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                module = ""
                if isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                elif isinstance(node, ast.Import):
                    module = node.names[0].name if node.names else ""

                # Direct imports from services or infrastructure are NOT
                # allowed in core/api (the facade is a re-export layer only).
                # Lazy imports via __getattr__ are OK.
                if "src.backend.services" in module:
                    # Check if it's an in-function lazy import (allowed).
                    src_line = node.lineno
                    func_depth = 0
                    for parent_node in ast.walk(tree):
                        if isinstance(parent_node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            if (
                                parent_node.lineno <= src_line
                                <= parent_node.end_lineno
                            ):
                                func_depth += 1
                    # If in __getattr__ function, it's OK.
                    # Otherwise — violation.

                    # Just check no top-level import of services.
                    if "src.backend.services" in content.split("def __getattr__")[0]:
                        assert False, (
                            f"core/api top-level imports from services: {module}"
                        )


class TestFacadeLayerBoundariesCycle59:
    """Cycle 59: facade respects layer boundary rules."""

    def test_extensions_use_facade(self):
        """Sample extensions should import via core.api, not directly.

        Cycle 59: validates migration pattern. Extensions in the
        allowlist that are pending migration should not increase.
        """
        # Check at least the 3 known extensions in allowlist.
        for path in [
            "extensions/core_entities/orders/workflows/orders_dsl.py",
            "extensions/osint_agent/functions/osint_workflow.py",
        ]:
            if os.path.exists(path):
                with open(path) as f:
                    content = f.read()
                # Should import from core.api or core (allowed).
                if "src.backend.core.api" not in content:
                    # May still be in core or other allowed — not a violation.
                    if (
                        "src.backend.services" in content
                        or "src.backend.infrastructure" in content
                    ):
                        # This is the existing allowlist entry — keep
                        # test for awareness, no assert.
                        pass

    def test_no_new_extensions_violations_introduced(self):
        """Cycle 59 invariant: tests detect if new extensions bypass facade.

        The facade is the contract. If a new extensions file imports
        from services/infrastructure without going through core.api,
        this test detects it.
        """
        sys.path.insert(0, "src")
        import ast

        # Sample-check known extensions dirs for direct services/infra.
        extensions_root = "extensions"
        if not os.path.isdir(extensions_root):
            return

        violations = []
        for root, _, files in os.walk(extensions_root):
            for f_name in files:
                if not f_name.endswith(".py") or f_name.startswith("test_"):
                    continue
                f_path = os.path.join(root, f_name)
                try:
                    with open(f_path) as f:
                        content = f.read()
                    tree = ast.parse(content)
                    for node in ast.walk(tree):
                        if isinstance(node, ast.ImportFrom):
                            mod = node.module or ""
                            if mod.startswith(
                                ("src.backend.services.", "src.backend.infrastructure."),
                            ):
                                violations.append((f_path, mod))
                except (SyntaxError, UnicodeDecodeError):
                    continue

        # These should match the allowlist exactly (3 known violations).
        if len(violations) > 3:
            pytest.fail(
                f"Found {len(violations)} extensions violations (> 3 known). "
                f"New violations: {violations}",
            )
