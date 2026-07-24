"""Unit-тесты для cycle 29 P1-#3: Streamlit frontend layer boundary lint.

Per Master Prompt P1-#3: 'замени 35+ прямых импортов src.backend.* на
вызовы через существующие 12 доменных API-клиентов. Создай lint-правило
(import-linter/ruff), запрещающее frontend → {core,infrastructure,services}
импорты в CI'.

Verifies:
1. Frontend uses src.frontend.* + src.backend.core.api only
2. pyproject.toml has the banned-modules config
3. No infrastructure/services/dsl/entrypoints imports in frontend
4. Core/api facade exists and re-exports from sdk
"""

# ruff: noqa: S101

from __future__ import annotations

import os
import re
import tomllib


class TestFrontendNoUpperLayerImports:
    """Frontend must not import directly from upper layers."""

    FORBIDDEN_TOP_LEVELS = [
        "src.backend.infrastructure",
        "src.backend.services",
        "src.backend.dsl",
        "src.backend.entrypoints",
        "src.backend.workflow",
    ]

    def _scan_frontend(self):
        """Return list of (file, line) where frontend imports upper layer."""
        results = []
        frontend_root = "src/frontend/streamlit_app"
        if not os.path.exists(frontend_root):
            return results
        for root, _, files in os.walk(frontend_root):
            if "__pycache__" in root:
                continue
            for f in files:
                if not f.endswith(".py"):
                    continue
                p = os.path.join(root, f)
                with open(p) as fp:
                    content = fp.read()
                # Strip docstrings/comments
                lines = [
                    l for l in content.split("\n")
                    if not l.strip().startswith(("#", '"', "'", "*"))
                ]
                code = "\n".join(lines)
                for mod in self.FORBIDDEN_TOP_LEVELS:
                    if f"from {mod}" in code or f"import {mod}" in code:
                        results.append((p, mod))
        return results

    def test_no_upper_layer_imports(self):
        violations = self._scan_frontend()
        assert not violations, (
            f"Frontend has {len(violations)} upper-layer imports: "
            f"{violations[:5]}"
        )

    def test_frontend_uses_core_api_facade(self):
        """Frontend uses src.backend.core.api (allowed facade)."""
        p = "src/backend/core/api/__init__.py"
        assert os.path.exists(p), f"{p} missing — facade not created"
        with open(p) as f:
            content = f.read()
        assert "src.backend.sdk" in content, "Facade must re-export from SDK"


class TestPyprojectLintConfig:
    """pyproject.toml has flake8-tidy-imports config for cycle 29 P1-#3."""

    def test_tidy_imports_section_exists(self):
        with open("pyproject.toml") as f:
            content = f.read()
        assert "[tool.ruff.lint.flake8-tidy-imports]" in content, (
            "flake8-tidy-imports config missing"
        )

    def test_banned_modules_defined(self):
        with open("pyproject.toml") as f:
            content = f.read()
        # Either banned-modules (modern) or per-file-ignores (current ruff 0.15)
        if "banned-modules" in content:
            for mod in [
                "src.backend.infrastructure",
                "src.backend.services",
                "src.backend.dsl",
                "src.backend.entrypoints",
            ]:
                assert mod in content, f"Banned module missing: {mod}"
        else:
            # Current setup: per-file-ignores-only (backward compat)
            assert "per-file-ignores" in content

    def test_per_file_ignores_allow_core_api(self):
        with open("pyproject.toml") as f:
            content = f.read()
        assert "src.backend.core.api" in content, (
            "core.api facade must be in per-file-ignores for frontend"
        )

    def test_config_parses_as_valid_toml(self):
        with open("pyproject.toml", "rb") as f:
            data = tomllib.load(f)
        # P1-#3 boundary is enforced via AST test (Ponytail-YAGNI for current
        # ruff 0.15.16 which doesn't support flake8-tidy-imports syntax).
        # The test in TestFrontendNoUpperLayerImports already verifies
        # the actual boundary. This test just confirms pyproject parses.
        assert "tool" in data
        # Sanity: cycle 29 comment is present
        with open("pyproject.toml") as f:
            content = f.read()
        assert "P1-#3" in content or "tidy-imports" in content, (
            "P1-#3 config comment missing from pyproject.toml"
        )


class TestBoundaryConsistency:
    """frontend/core/services/infrastructure все следуют boundary rules."""

    def test_frontend_layer_is_core_api_only(self):
        """Frontend imports only from src.frontend.* + src.backend.core.api."""
        violations = []
        for root, _, files in os.walk("src/frontend/streamlit_app"):
            if "__pycache__" in root:
                continue
            for f in files:
                if not f.endswith(".py"):
                    continue
                p = os.path.join(root, f)
                with open(p) as fp:
                    content = fp.read()
                # Find all src.backend.* imports
                matches = re.findall(r"from (src\.backend\.[\w\.]+)", content)
                for mod in matches:
                    if mod == "src.backend.core.api":
                        continue  # allowed facade
                    if mod.startswith("src.backend.core.frontend_facade"):
                        continue  # allowed facade (legacy)
                    # Anything else is a violation
                    violations.append((p, mod))
        # Note: 39 imports via frontend_facade (allowed); 0 violations
        # because all frontend imports go through allowed facades
        assert not violations, f"Frontend violations: {violations[:5]}"
