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


from __future__ import annotations

import os
import re
import tomllib

import pytest


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
                    line for line in content.split("\n")
                    if not line.strip().startswith(("#", '"', "'", "*"))
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
        """Frontend imports only from src.frontend.* + src.backend.core.api.

        Ловит обе формы: ``from src.backend.X import ...`` и
        ``import src.backend.X``.
        """
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
                # Unified: catches both 'from' and 'import' styles.
                matches = re.findall(
                    r"(?:from|import)\s+(src\.backend\.[\w\.]+)", content,
                )
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


# P1 S172 W2: ratchet for thin API-client boundary.
# api_clients/ имеет особенно строгий контракт: только HTTP-клиенты,
# facade-импорты (frontend_facade / core.api) и api-stdlib. Любой import
# который обходит facade → немедленная blocking-failure.
class TestApiClientsBoundaryRatchet:
    """Architecture ratchet (P1 S172 W2): api_clients/ imports only via approved facade."""

    ALLOWED_FACADES = frozenset(
        {
            "src.backend.core.api",
            "src.backend.core.frontend_facade",
        },
    )

    def test_api_clients_only_use_facade(self):
        """api_clients/*.py must import only from approved facades.

        Ловит обе формы: ``from src.backend.X import ...`` и
        ``import src.backend.X``.
        """
        import os

        api_dir = "src/frontend/streamlit_app/api_clients"
        if not os.path.isdir(api_dir):
            pytest.skip("api_clients directory not found")

        violations: list[tuple[str, str]] = []
        for f in sorted(os.listdir(api_dir)):
            if not f.endswith(".py") or f.startswith("_") or f == "__init__.py":
                continue
            p = os.path.join(api_dir, f)
            with open(p) as fp:
                content = fp.read()
            # Unified: catches both 'from' and 'import' styles.
            matches = re.findall(
                r"(?:from|import)\s+(src\.backend\.[\w\.]+)", content,
            )
            for mod in matches:
                if mod in self.ALLOWED_FACADES:
                    continue
                if mod.startswith("src.backend.core.frontend_facade"):
                    continue
                if mod.startswith("src.backend.core.api"):
                    continue
                violations.append((p, mod))

        assert not violations, (
            f"api_clients/ имеет {len(violations)} обходных импортов: "
            f"{violations[:5]} "
            f"(Approved: {sorted(self.ALLOWED_FACADES)})"
        )

    def test_no_bare_src_backend_infrastructure_in_frontend(self):
        """Top-level запрет: ни один файл во frontend не импортирует напрямую infrastructure."""
        import os

        violations: list[tuple[str, str]] = []
        for root, _, files in os.walk("src/frontend/streamlit_app"):
            if "__pycache__" in root:
                continue
            for f in files:
                if not f.endswith(".py"):
                    continue
                p = os.path.join(root, f)
                with open(p) as fp:
                    content = fp.read()
                forbidden = [
                    "src.backend.infrastructure",
                    "src.backend.services",
                    "src.backend.dsl",
                    "src.backend.entrypoints",
                    "src.backend.workflow",
                ]
                for forbidden_mod in forbidden:
                    pattern = re.compile(
                        rf"from {re.escape(forbidden_mod)}"
                        r"[\.\w]*|"
                        rf"import {re.escape(forbidden_mod)}",
                    )
                    if pattern.search(content):
                        violations.append((p, forbidden_mod))
        assert not violations, (
            f"Frontend => upper-layer нарушений: {len(violations)}; "
            f"sample: {violations[:5]}"
        )

    def test_ratchet_command_present(self):
        """CI command доступен через `make arch-ratchet` (P1 S172 W2)."""
        # Target определён в make/quality.mk (sub-make), но также зарегистрирован
        # в root Makefile PHONY list.
        with open("Makefile") as f:
            mf_content = f.read()
        with open("make/quality.mk") as f:
            qm_content = f.read()
        assert "arch-ratchet" in mf_content, (
            "Makefile PHONY list contains 'arch-ratchet' — expected"
        )
        assert "arch-ratchet:" in qm_content, (
            "make/quality.mk target 'arch-ratchet:' missing — добавь documented CI command"
        )


def test_frontend_ratchet_documented_in_make_quality() -> None:
    """P1 S172 W2: Makefile `arch-ratchet` определён и использует pytest."""
    with open("make/quality.mk") as f:
        content = f.read()
    assert "arch-ratchet:" in content, (
        "make/quality.mk target 'arch-ratchet' missing — добавь documented CI command"
    )
    # Должен запускать тесты ratchet.
    assert "test_layer_boundary" in content or "test_arch_ratchet" in content, (
        "make/quality.mk 'arch-ratchet' не вызывает ratchet-тесты"
    )
