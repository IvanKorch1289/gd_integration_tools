"""Unit-тесты для core/api facade (cycle 29, Master Prompt P1-#1).

Self-contained — does NOT import deps that require chain infrastructure
(Vault, FastAPI app, etc.). Tests facade re-exports + lazy loads.
"""


from __future__ import annotations

import os
import sys


class TestFacadeExists:
    """The core/api/__init__.py must exist as canonical public API."""

    def test_facade_file_exists(self):
        path = "src/backend/core/api/__init__.py"
        assert os.path.exists(path), f"{path} missing"

    def test_facade_module_parses(self):
        with open("src/backend/core/api/__init__.py") as f:
            content = f.read()
        import ast
        ast.parse(content)

    def test_facade_has_explicit_all(self):
        """Facade must have __all__ to make public API explicit."""
        with open("src/backend/core/api/__init__.py") as f:
            content = f.read()
        assert "__all__" in content
        # Must include 4 new categories per Master Prompt
        all_section = content[content.find("__all__"):]
        for required in [
            "get_scheduler_provider",  # DI providers
            "AIGateway",  # AI entry
            "SchedulerManager",  # production scheduler
            "WorkflowBuilder",  # DSL workflow
        ]:
            assert required in all_section, f"Missing from __all__: {required}"


class TestFacadeReExports:
    """Facade must re-export from src.backend.sdk (no duplication)."""

    def test_docstring_references_sdk(self):
        path = "src/backend/core/api/__init__.py"
        with open(path) as f:
            content = f.read()
        # Facade must reference SDK as the primary source
        assert "src.backend.sdk" in content, "Facade must re-export from SDK"

    def test_facade_no_second_implementation(self):
        """Facade is THIN — it must not define classes, only re-export."""
        with open("src/backend/core/api/__init__.py") as f:
            content = f.read()
        # No class definitions allowed
        assert "class " not in content, (
            "Facade must not define new classes — only re-export from SDK"
        )


class TestFacadeRuntime:
    """Facade exports work at runtime (lazy-loaded)."""

    def test_facade_imports_cleanly(self):
        """Import facade — must work even with chain deps absent."""
        sys.path.insert(0, "src")
        import src.backend.core.api

        # All __all__ exports must be accessible
        for name in src.backend.core.api.__all__:
            assert hasattr(src.backend.core.api, name), f"Missing export: {name}"

    def test_lazy_loads_work(self):
        """DI providers + AIGateway + SchedulerManager lazy-load via __getattr__."""
        sys.path.insert(0, "src")
        import src.backend.core.api

        # Force lazy access — must work
        for name in [
            "get_scheduler_provider",
            "get_redis_client_class",
            "AIGateway",
        ]:
            obj = getattr(src.backend.core.api, name)
            assert obj is not None, f"Lazy load failed for: {name}"

    def test_tab_completion_includes_lazy_exports(self):
        """__dir__() must include __getattr__ symbols for IDE support."""
        sys.path.insert(0, "src")
        import src.backend.core.api

        d = dir(src.backend.core.api)
        for name in [
            "get_scheduler_provider",
            "AIGateway",
        ]:
            assert name in d, f"{name} missing from dir() — tab completion broken"


class TestBoundaryRule:
    """extensions → core/api only (per DEEP_AUDIT_REPORT R3.10d)."""

    def test_facade_documents_boundary(self):
        path = "src/backend/core/api/__init__.py"
        with open(path) as f:
            content = f.read()
        # Must document the boundary rule
        assert "extensions" in content
        assert "core.api" in content or "core/api" in content
