"""Unit-тесты для cycle 30 P3 + P4 closures.

P3: Browser RPA full DSL builder methods (browser_launch, wait_for_selector, print_pdf)
P4-#3: vulture CI gate target exists in Makefile
P4-#4: Protocol definitions exist in RouteBuilder module
"""

# ruff: noqa: S101

from __future__ import annotations

import os


class TestBrowserRPABuilderMethods:
    """P3: Builder must have all browser RPA methods."""

    def test_browser_launch_exists(self):
        path = "src/backend/dsl/builders/ai_rpa/rpa.py"
        with open(path) as f:
            content = f.read()
        assert "def browser_launch" in content, (
            "browser_launch builder method missing (P3 gap)"
        )

    def test_wait_for_selector_exists(self):
        path = "src/backend/dsl/builders/ai_rpa/rpa.py"
        with open(path) as f:
            content = f.read()
        assert "def wait_for_selector" in content, (
            "wait_for_selector builder method missing (P3 gap)"
        )

    def test_print_pdf_exists(self):
        path = "src/backend/dsl/builders/ai_rpa/rpa.py"
        with open(path) as f:
            content = f.read()
        assert "def print_pdf" in content, (
            "print_pdf builder method missing (P3 gap)"
        )

    def test_existing_methods_preserved(self):
        """navigate, click, fill_form, screenshot, extract must still exist."""
        path = "src/backend/dsl/builders/ai_rpa/rpa.py"
        with open(path) as f:
            content = f.read()
        for method in ["def navigate", "def click", "def fill_form",
                       "def screenshot", "def extract"]:
            assert method in content, f"Existing method missing: {method}"


class TestBrowserRPAProcessors:
    """P3: All 8 processors must exist in rpa_browser.py."""

    def test_all_processors_present(self):
        path = "src/backend/dsl/engine/processors/rpa_browser.py"
        assert os.path.exists(path), f"{path} missing"
        with open(path) as f:
            content = f.read()
        for cls in ["BrowserLaunchProcessor", "NavigateProcessor",
                    "ClickProcessor", "FillProcessor", "ExtractProcessor",
                    "WaitForProcessor", "ScreenshotProcessor", "PdfProcessor"]:
            assert cls in content, f"Processor class missing: {cls}"


class TestVultureGate:
    """P4-#3: vulture-gate target must exist in Makefile."""

    def test_vulture_gate_target(self):
        path = "make/quality.mk"
        with open(path) as f:
            content = f.read()
        assert "vulture-gate:" in content, (
            "vulture-gate target missing from Makefile"
        )
        assert "--min-confidence 80" in content, (
            "vulture-gate must use --min-confidence 80"
        )

    def test_existing_vulture_check_preserved(self):
        path = "make/quality.mk"
        with open(path) as f:
            content = f.read()
        assert "vulture-check:" in content, (
            "vulture-check (non-blocking) target removed"
        )


class TestRouteBuilderProtocols:
    """P4-#4: Protocol definitions must exist in RouteBuilder module."""

    def test_protocol_imports_present(self):
        path = "src/backend/dsl/builders/base/__init__.py"
        with open(path) as f:
            content = f.read()
        assert "Protocol" in content, (
            "Protocol import missing from RouteBuilder module"
        )
        assert "runtime_checkable" in content

    def test_protocol_definitions_exist(self):
        path = "src/backend/dsl/builders/base/__init__.py"
        with open(path) as f:
            content = f.read()
        assert "_RouteProcessorSteps" in content
        assert "_RouteCore" in content

    def test_migration_path_documented(self):
        path = "src/backend/dsl/builders/base/__init__.py"
        with open(path) as f:
            content = f.read()
        assert "Migration path" in content or "CompositionRouteBuilder" in content


class TestDSLProcessorsDirSplit:
    """P4-#1: DSL processors directory split (additive, non-breaking)."""

    def test_db_subdir_exists(self):
        """db/ subdir must exist with re-exports."""
        path = "src/backend/dsl/engine/processors/db/__init__.py"
        assert os.path.exists(path), f"{path} missing"

    def test_db_subdir_reexports(self):
        """db/ must re-export all 3 DB processors."""
        path = "src/backend/dsl/engine/processors/db/__init__.py"
        with open(path) as f:
            content = f.read()
        for cls in ["DbCallProcedureProcessor", "DbCrudProcessor",
                    "DbQueryExternalProcessor"]:
            assert cls in content, f"Missing re-export: {cls}"

    def test_flat_files_still_work(self):
        """Existing flat imports must not be broken (additive pattern)."""
        for f in ["db_call_procedure.py", "db_crud.py", "db_query_external.py"]:
            path = f"src/backend/dsl/engine/processors/{f}"
            assert os.path.exists(path), f"Flat file removed (should still exist): {f}"
